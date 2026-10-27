"""Package cross-ISA raw attempts with source, debug, trace and binary evidence."""
import argparse
import ast
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import tarfile


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda:f.read(1024*1024), b''):
            h.update(data)
    return h.hexdigest()


def trace_events(path, build_folder):
    events, unparsed = [], []
    pattern = re.compile(r'^\s*(\d+)\s+execve\(("(?:\\.|[^"\\])*"), (\[.*\]), .*\)\s+=\s+(-?\d+)')
    for line in path.read_text().splitlines():
        if 'execve(' not in line:
            continue
        match = pattern.match(line)
        if not match:
            unparsed.append(line)
            continue
        try:
            executable, argv = ast.literal_eval(match.group(2)), ast.literal_eval(match.group(3))
        except (SyntaxError, ValueError):
            unparsed.append(line)
            continue
        name = Path(executable).name
        role = ('frontend' if name in ('cc1','cc1plus') else
                'assembler' if name == 'as' or name.endswith('-as') else
                'link_driver' if name == 'collect2' else
                'lto' if name in ('lto1','lto-wrapper') else
                'linker' if name in ('ld','ld.lld','lld') or name.endswith('-ld') else
                'driver' if 'gcc' in name or 'g++' in name or 'clang' in name else 'other')
        def normalized(s):
            s = s.replace(build_folder, 'BUILD').replace('/input/sources/', 'SOURCE/')
            return re.sub(r'/tmp/cc[A-Za-z0-9]+(\.[A-Za-z0-9]+)', r'<TMP>/compiler-temp\1', s)
        events.append({'pid':int(match.group(1)), 'executable':executable, 'role':role,
                       'argv':argv, 'normalized_argv':[normalized(x) for x in argv],
                       'execve_returncode':int(match.group(4))})
    return {'events':events,'unparsed_execve_lines':unparsed,'raw_trace':path.name}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--qualification', required=True, type=Path)
    parser.add_argument('--repo', default='sjkim1127/decbench-multilang-corpus')
    parser.add_argument('--revision', required=True)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    import pyarrow as pa
    import pyarrow.parquet as pq
    corpus = args.corpus.resolve()
    destination = args.output.resolve()
    if destination.exists():
        raise ValueError('Use a fresh package directory')
    destination.mkdir(parents=True)
    data = destination/'data'; data.mkdir()
    payloads = destination/'payloads'; payloads.mkdir()
    metadata, indexes, pairs, tools_dir = [], [], {}, destination/'collection'
    tools_dir.mkdir()
    for name in ('image.json','environment.json','summary.json','toolchain-version-correction.json'):
        (tools_dir/name).write_bytes((corpus/name).read_bytes())
    root = Path(__file__).resolve().parents[1]
    for name in ('scripts/prepare_cross_isa.py','scripts/container_cross_isa.py','scripts/publish_cross_isa.py',
                 'docker/cross-isa.Dockerfile','configs/native-projects.json',
                 'schemas/qualification-record.schema.json','docs/QUALIFICATION_DESIGN.md','docs/CROSS_ISA_REPORT.md',
                 'scripts/qualify_elf_pilot.py'):
        p = tools_dir/name; p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((root/name).read_bytes())
    for p in args.qualification.iterdir():
        if p.is_file():
            target = destination/'qualification-pilot'/p.name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(p.read_bytes())
    for cell in sorted(p for p in corpus.iterdir() if (p/'attempts.jsonl').exists()):
        rows = [json.loads(line) for line in (cell/'attempts.jsonl').read_text().splitlines()]
        shard = 'payloads/'+cell.name+'.tar.gz'
        files = {cell/'attempts.jsonl'}
        for row in rows:
            folder = cell/'builds'/row['project']/row['profile']/str(row['attempt'])
            files.add(folder/'manifest.json')
            snapshot = cell/row['source']['snapshot_path']
            if sha(snapshot) != row['source']['snapshot_sha256']:
                raise ValueError('Upstream archive mismatch')
            files.add(snapshot)
            for artifact in row['artifacts']:
                f = cell/artifact['path']
                if sha(f)!=artifact['sha256'] or f.stat().st_size!=artifact['size']:
                    raise ValueError('Changed artifact: '+str(f))
                files.add(f)
            traces = []
            for command in row['commands'][:2]:
                filename = command.get('execve_trace_path')
                if filename:
                    traces.append(trace_events(folder/filename, str(folder).replace(str(corpus), '/out')))
            if row['status'] == 'success' and (len(traces)!=2 or any(t['unparsed_execve_lines'] for t in traces)):
                raise ValueError('Incomplete execve capture or parsing: '+str(folder))
            normalized_trace = folder/'child-argv.normalized.json'
            normalized_trace.write_text(json.dumps(traces,indent=2)+'\n')
            files.add(normalized_trace)
            metadata_manifest = dict(row)
            if row['toolchain']['linker']['returncode'] != 0:
                metadata_manifest['toolchain_version_correction'] = json.loads(
                    (corpus/'toolchain-version-correction.json').read_text())
            meta = {'schema_version':row['schema_version'],'build_id':row['build_id'],
                'project':row['project'],'language':row['language'],'os':'linux','format':'elf',
                'arch':row['target']['arch'],'abi':row['target']['abi'],
                'profile':row['profile'],'attempt':row['attempt'],
                'status':row['status'],'qualified':False,'split_group':row['split_group'],
                'payload_shard':shard,'manifest_member':(folder/'manifest.json').relative_to(cell).as_posix(),
                'manifest_json':json.dumps(metadata_manifest,sort_keys=True), 'replay_json':None}
            metadata.append(meta)
            pairs.setdefault(row['build_id'], []).append(row)
        tarpath = destination/shard
        with tarpath.open('wb') as raw:
            with gzip.GzipFile(fileobj=raw, mode='wb', compresslevel=3, mtime=0, filename='') as compressed:
                with tarfile.open(fileobj=compressed,mode='w|',format=tarfile.PAX_FORMAT) as tf:
                    for p in sorted(files):
                        name = p.relative_to(cell).as_posix()
                        info = tarfile.TarInfo(name);info.size=p.stat().st_size;info.mode=0o644
                        with p.open('rb') as file: tf.addfile(info,file)
                        indexes.append({'shard':shard,'member':name,'sha256':sha(p),'size':info.size})
        print('Packaged',cell.name,len(rows),'records',tarpath.stat().st_size,'bytes',flush=True)
    replay = []
    for identity, rows in sorted(pairs.items()):
        binary_hashes = [[a['sha256'] for a in r['artifacts'] if a['path'].endswith('binary.unstripped.so')]
                         for r in rows]
        replay.append({'build_id':identity, 'attempts':len(rows),
                       'binary_hash_equal':len(rows)==2 and all(binary_hashes) and binary_hashes[0]==binary_hashes[1]})
    replay_by_id = {r['build_id']:r for r in replay}
    for row in metadata:
        row['replay_json'] = json.dumps(replay_by_id[row['build_id']], sort_keys=True)
    pq.write_table(pa.Table.from_pylist(metadata),data/'attempts.parquet',compression='zstd')
    (destination/'artifact-index.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in indexes))
    (destination/'replays.json').write_text(json.dumps(replay,indent=2)+'\n')
    summary={'campaign':'cross-isa-2026-10-28','attempts':len(metadata),
             'successful_attempts':sum(r['status']=='success' for r in metadata),
             'failed_attempts':sum(r['status']=='failed' for r in metadata),
             'variants':len(pairs),'replay_binary_equal_pairs':sum(r['binary_hash_equal'] for r in replay),
             'architectures':dict(Counter(r['arch'] for r in metadata)),
             'compilers':dict(Counter(json.loads(r['manifest_json'])['toolchain']['family'] for r in metadata)),
             'qualified':0,'source_authored_by_collector':False,'produced_program_execution':False}
    (destination/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    checks = [{'path':p.relative_to(destination).as_posix(),'sha256':sha(p),'size':p.stat().st_size}
              for p in sorted(destination.rglob('*')) if p.is_file()]
    (destination/'checksums.json').write_text(json.dumps(checks,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)
    if args.publish:
        from huggingface_hub import HfApi
        api=HfApi(); head=api.repo_info(args.repo,repo_type='dataset').sha
        if head!=args.revision:
            raise ValueError('Dataset head changed; review before publishing')
        commit=api.upload_folder(repo_id=args.repo,repo_type='dataset',folder_path=destination,
            path_in_repo='native/cross-isa-2026-10-28',parent_commit=args.revision,
            commit_message='Add ARMv7 ARM Thumb and RISC-V64 raw compiler matrix')
        print('PUBLISHED',commit.oid,flush=True)


if __name__ == '__main__':
    main()
