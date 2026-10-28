"""Extract source/DWARF/symbol evidence for one C ELF; never auto-qualify."""
import argparse
from collections import Counter, defaultdict
import hashlib
import gzip
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import zlib

from elftools.dwarf.descriptions import describe_form_class
from elftools.elf.elffile import ELFFile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def text(value):
    return value.decode('utf-8', 'replace') if isinstance(value, bytes) else str(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--corpus', required=True, type=Path)
    parser.add_argument('--attempt', required=True, type=int)
    parser.add_argument('--source-file', required=True)
    parser.add_argument('--clang', default='/usr/bin/clang')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if Path(args.source_file).name != args.source_file or args.source_file in ('.', '..'):
        raise ValueError('Select one source file by basename')
    record = json.loads(args.manifest.read_text())
    if record['language'] != 'c' or record['target']['arch'] != 'x86_64':
        raise ValueError('This pilot only supports the initial x86-64 C ELF')
    root = args.corpus.resolve()
    attempt_path = root / record['reproducibility']['replay_paths'][args.attempt - 1]
    binary = attempt_path/'binary.unstripped.so'
    stripped = attempt_path/'binary.stripped.so'
    debug = attempt_path/'binary.debug'
    source_archive = root / record['source']['snapshot_path']
    source_archive_sha = digest(source_archive.read_bytes())
    if source_archive_sha != record['source']['snapshot_sha256']:
        raise ValueError('Source archive SHA-256 differs from original manifest')
    expected = {x['path']: x['sha256'] for x in record['artifacts']}
    for p in (binary, stripped, debug):
        if digest(p.read_bytes()) != expected[p.relative_to(root).as_posix()]:
            raise ValueError('Binary/debug bytes do not match manifest: ' + str(p))
    output = args.output.resolve()
    if output.exists():
        raise ValueError('Output already exists')
    output.mkdir(parents=True)
    clang = Path(args.clang).resolve()
    clang_version = subprocess.check_output([str(clang), '--version'], text=True)
    with tempfile.TemporaryDirectory(prefix='qualification-source-') as temporary:
        dest = Path(temporary)
        with tarfile.open(source_archive) as tf:
            tf.extractall(dest, filter='data')
        source = dest / args.source_file
        source_bytes = source.read_bytes()
        source_sha = digest(source_bytes)
        argv = [str(clang), '-std=c99', '-fsyntax-only', '-Xclang', '-ast-dump=json', str(source)]
        process = subprocess.run(argv, cwd=dest, capture_output=True, check=True)
        (output/'clang-ast.stderr').write_bytes(process.stderr)
        (output/'clang-ast.json.gz').write_bytes(gzip.compress(process.stdout, mtime=0))
        ast = json.loads(process.stdout)
        source_functions = []
        for node in ast.get('inner', []):
            if node.get('kind') != 'FunctionDecl' or not any(
                    item.get('kind') == 'CompoundStmt' for item in node.get('inner', [])):
                continue
            loc = node.get('loc', {})
            if loc.get('includedFrom') or loc.get('file', str(source)) != str(source):
                continue
            begin = node['range']['begin']
            begin = begin.get('expansionLoc', begin)
            end = node['range']['end']
            end = end.get('expansionLoc', end)
            if 'offset' not in begin or 'offset' not in end or 'offset' not in loc:
                continue
            start, stop = begin['offset'], end['offset'] + end.get('tokLen', 1)
            if not 0 <= start < stop <= len(source_bytes):
                continue
            name = node['name']
            name_offset = loc['offset']
            if source_bytes[name_offset:name_offset + len(name)] != name.encode():
                continue
            line = source_bytes[:name_offset].count(b'\n') + 1
            end_line = source_bytes[:stop].count(b'\n') + 1
            identity = {'source_commit':record['source']['commit_sha'], 'source_path':args.source_file,
                        'source_sha256':source_sha, 'name':name, 'start_byte':start, 'end_byte_exclusive':stop}
            source_functions.append({**identity, 'source_function_id':digest(json.dumps(identity,sort_keys=True).encode()),
                                     'decl_line':line, 'line_start':source_bytes[:start].count(b'\n')+1,
                                     'line_end':end_line, 'source_text':source_bytes[start:stop].decode('utf-8','replace')})
    ast_by_name = defaultdict(list)
    for item in source_functions:
        ast_by_name[item['name'], item['decl_line']].append(item)
    binary_sha, stripped_sha, debug_sha = [digest(p.read_bytes()) for p in (binary,stripped,debug)]
    with binary.open('rb') as bin_file, stripped.open('rb') as strip_file, debug.open('rb') as dbg_file:
        original, decompiler_input, sidecar = map(ELFFile, (bin_file,strip_file,dbg_file))
        if any(e.header['e_machine'] != 'EM_X86_64' or e.elfclass != 64 for e in (original,decompiler_input,sidecar)):
            raise ValueError('Unexpected ELF machine')
        section = decompiler_input.get_section_by_name('.gnu_debuglink')
        if section is None:
            raise ValueError('Stripped ELF has no GNU debuglink')
        raw = section.data(); end = raw.index(b'\0'); crcpos = (end + 4) & ~3
        expected_crc = int.from_bytes(raw[crcpos:crcpos+4], 'little')
        actual_crc = zlib.crc32(debug.read_bytes()) & 0xffffffff
        if raw[:end].decode() != debug.name or expected_crc != actual_crc:
            raise ValueError('GNU debuglink filename/CRC mismatch')
        orig_text = original.get_section_by_name('.text').data()
        strip_text = decompiler_input.get_section_by_name('.text').data()
        if orig_text != strip_text:
            raise ValueError('Original and stripped .text differ')
        symbols = defaultdict(list)
        symtab = original.get_section_by_name('.symtab')
        if symtab is None or not sidecar.has_dwarf_info():
            raise ValueError('Missing symbol table or debug info')
        for symbol in symtab.iter_symbols():
            if symbol['st_info']['type'] == 'STT_FUNC' and symbol['st_size']:
                symbols[symbol['st_value']].append({'name':symbol.name,'size':symbol['st_size']})
        dwarf = sidecar.get_dwarf_info()
        rows = []
        for cu in dwarf.iter_CUs():
            program = dwarf.line_program_for_CU(cu)
            files = program['file_entry'] if program else []
            for die in cu.iter_DIEs():
                if die.tag != 'DW_TAG_subprogram' or die.attributes.get('DW_AT_declaration', None) and die.attributes['DW_AT_declaration'].value:
                    continue
                attrs = die.attributes
                name = text(attrs['DW_AT_name'].value) if 'DW_AT_name' in attrs else None
                low = attrs['DW_AT_low_pc'].value if 'DW_AT_low_pc' in attrs else None
                high = attrs.get('DW_AT_high_pc')
                size = (high.value if describe_form_class(high.form) == 'constant' else high.value-low) if high and low is not None else None
                size = size if size is not None and size > 0 else None
                line = attrs['DW_AT_decl_line'].value if 'DW_AT_decl_line' in attrs else None
                file_index = attrs['DW_AT_decl_file'].value if 'DW_AT_decl_file' in attrs else 0
                file_name = text(files[file_index-1].name) if 0 < file_index <= len(files) else None
                # A basename is accepted only for the single explicitly selected source path.
                path_ok = file_name == args.source_file and '/' not in args.source_file
                matches = ast_by_name.get((name, line), []) if path_ok else []
                sym = symbols.get(low, []) if low is not None else []
                exact = [s for s in sym if s['name'] == name and s['size'] == size]
                candidate = len(matches) == 1 and len(sym) == 1 and len(exact) == 1
                match = matches[0] if len(matches) == 1 else None
                missing = []
                if not path_ok: missing.append('source path unresolved or outside selected file')
                if len(matches) != 1: missing.append('source AST name/line is absent or ambiguous')
                if len(sym) != 1 or len(exact) != 1: missing.append('ELF symbol extent/name is absent or ambiguous')
                if candidate: missing.append('independent boundary, transformations and semantic oracle not verified')
                rows.append({'schema_version':'qualification-0.1.0', 'binary_sha256':binary_sha,
                    'decompiler_input_sha256':stripped_sha, 'debug_sha256':debug_sha,
                    'source_commit':record['source']['commit_sha'],
                    'source_function_id':match['source_function_id'] if match else None,
                    'binary_function_va':low, 'binary_function_size':size, 'address_kind':'elf-linked-va',
                    'source_path':args.source_file if path_ok else None,
                    'source_line_start':match['line_start'] if match else line,
                    'source_line_end':match['line_end'] if match else None,
                    'inlined':None, 'outlined':None,
                    'compiler_generated':True if attrs.get('DW_AT_artificial') and attrs['DW_AT_artificial'].value else None,
                    'mapping_method':'dwarf-declaration+elf-symbol+independent-clang-ast',
                    'mapping_evidence':{'die_offset':die.offset,'compilation_unit_offset':cu.cu_offset,
                        'dwarf_name':name,'dwarf_decl_file':file_name,'dwarf_decl_line':line,
                        'dwarf_inline_attribute':attrs['DW_AT_inline'].value if 'DW_AT_inline' in attrs else None,
                        'symbol_entries_at_address':sym,'source_sha256':source_sha,
                        'source_archive_sha256':source_archive_sha, 'debuglink_crc32':f'{actual_crc:08x}',
                        'original_text_sha256':digest(orig_text)},
                    'oracle_status':'candidate' if candidate else 'unassessed', 'oracle_confidence':None,
                    'qualification_reason':'; '.join(missing), 'qualified':False,
                    'eligibility_gates':{'debug_association_verified':True,'source_body_extracted':match is not None,
                        'boundary_independently_verified':False,'unique_mapping_verified':False,
                        'transformations_reviewed':False,'semantic_oracle_verified':False}})
    (output/'source-functions.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in source_functions))
    (output/'function-candidates.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in rows))
    report = {'scope':'one original C ELF pilot; candidates are not qualified', 'binary_sha256':binary_sha,
        'stripped_sha256':stripped_sha, 'debug_sha256':debug_sha,'source_commit':record['source']['commit_sha'],
        'source_archive_sha256':source_archive_sha,'source_file_sha256':source_sha,
        'debuglink_crc32':f'{actual_crc:08x}', 'text_equal':True,
        'clang_path':str(clang),'clang_sha256':digest(clang.read_bytes()),'clang_version':clang_version,
        'clang_argv':argv, 'clang_ast_sha256_uncompressed':digest(process.stdout),
        'source_functions':len(source_functions),'dwarf_subprogram_records':len(rows),
        'status_counts':dict(Counter(r['oracle_status'] for r in rows)),
        'qualified':0, 'limitations':['parser environment differs from original build','no independent machine boundary analysis',
                                      'no inline/outline/folding assessment','no semantic oracle']}
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
