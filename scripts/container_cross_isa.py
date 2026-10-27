"""Compile upstream sources for ARM/Thumb/RISC-V without running output binaries."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time
import zlib

INPUT = Path('/input')
OUT = Path('/out')
SOURCES = json.loads((INPUT / 'sources.json').read_text())
IMAGE_ID = os.environ['CORPUS_IMAGE_ID']
ENV = {'PATH': '/usr/bin:/bin', 'HOME': '/tmp', 'LANG': 'C', 'LC_ALL': 'C',
       'SOURCE_DATE_EPOCH': '0', 'TMPDIR': '/tmp'}
PROFILES = {
    'O0': ['-O0'], 'O1': ['-O1'], 'O2': ['-O2'], 'O3': ['-O3'],
    'Os': ['-Os'], 'Oz': ['-Oz'], 'O2-noinline': ['-O2', '-fno-inline'],
    'O2-LTO': ['-O2', '-flto'], 'O2-ThinLTO': ['-O2', '-flto=thin'],
}
CELLS = [
    ('armv7', 'arm', 'arm-linux-gnueabihf', ['-march=armv7-a', '-marm', '-mfloat-abi=hard', '-mfpu=vfpv3-d16']),
    ('armv7', 'thumb', 'arm-linux-gnueabihf', ['-march=armv7-a', '-mthumb', '-mfloat-abi=hard', '-mfpu=vfpv3-d16']),
    ('riscv64', 'rv64gc', 'riscv64-linux-gnu', ['-march=rv64gc', '-mabi=lp64d']),
]

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def version(program, args=('--version',)):
    path = Path(shutil.which(program)).resolve()
    r = subprocess.run([str(path), *args], env=ENV, capture_output=True, text=True, timeout=60)
    return {'requested_executable': program, 'path': str(path), 'sha256': sha(path),
            'argv': [str(path), *args], 'returncode': r.returncode,
            'stdout': r.stdout, 'stderr': r.stderr}

tools = {name: version(name) for name in ['clang', 'clang++', 'ld.lld',
    'arm-linux-gnueabihf-gcc', 'arm-linux-gnueabihf-g++',
    'riscv64-linux-gnu-gcc', 'riscv64-linux-gnu-g++',
    'arm-linux-gnueabihf-ld', 'riscv64-linux-gnu-ld',
    'arm-linux-gnueabihf-objcopy', 'riscv64-linux-gnu-objcopy',
    'arm-linux-gnueabihf-readelf', 'riscv64-linux-gnu-readelf', 'strace']}
dpkg = subprocess.run(['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\n'], env=ENV,
                      capture_output=True, text=True, check=True)
environment = {'image_id': IMAGE_ID, 'tools': tools, 'packages': dpkg.stdout,
               'environment': ENV, 'network': 'docker-network-none',
               'produced_program_execution': False}
OUT.mkdir(parents=True, exist_ok=True)
(OUT / 'environment.json').write_text(json.dumps(environment, indent=2) + '\n')

def run(folder, number, argv, cwd='/input', trace=False):
    trace_path = folder / f'command-{number}.execve.trace'
    actual = (['strace', '-f', '-e', 'trace=execve', '-s', '32768', '-o', str(trace_path), '--']
              if trace else []) + [str(x) for x in argv]
    begin = time.monotonic()
    try:
        result = subprocess.run(actual, cwd=cwd, env=ENV, capture_output=True, timeout=600)
        stdout, stderr, rc = result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as exc:
        stdout, stderr, rc = exc.stdout or b'', exc.stderr or b'', None
    (folder / f'command-{number}.stdout').write_bytes(stdout)
    (folder / f'command-{number}.stderr').write_bytes(stderr)
    return {'argv': [str(x) for x in argv], 'cwd': str(cwd), 'returncode': rc,
            'duration_seconds': round(time.monotonic()-begin, 3),
            'stdout_path': f'command-{number}.stdout', 'stderr_path': f'command-{number}.stderr',
            'execve_trace_path': trace_path.name if trace and trace_path.exists() else None}

def compile_one(job):
    project, (arch, isa, triple, machine_flags), family, profile, attempt = job
    cell = f'{arch}-{isa}-{family}'
    out = OUT / cell / 'builds' / project['id'] / profile / str(attempt)
    out.mkdir(parents=True, exist_ok=False)
    source = INPUT / 'sources' / project['id'] / project['source_file']
    cxx = project['language'] == 'cpp'
    driver_name = ('clang++' if cxx else 'clang') if family == 'clang' else triple + ('-g++' if cxx else '-gcc')
    driver = '/usr/bin/' + driver_name
    flag = PROFILES[profile]
    target_flags = (['--target=' + triple, '--gcc-toolchain=/usr'] if family == 'clang' else []) + machine_flags
    compile_args = [driver, *target_flags, '-std=' + project['standard'], *flag, '-g', '-gdwarf-4', '-fPIC',
                    '-ffile-prefix-map=/input/sources=SOURCE', '-fdebug-prefix-map=/input/sources=SOURCE',
                    '-v', '-c', str(source), '-o', str(out / 'unit.o')]
    link_args = [driver, *target_flags, *flag, '-v', '-shared']
    if family == 'clang' and 'LTO' in profile:
        link_args += ['-fuse-ld=lld']
    link_args += [str(out / 'unit.o'), '-o', str(out / 'binary.unstripped.so')]
    identity = {'schema_version':'cross-isa-0.1', 'source_commit': project['commit_sha'],
                'source_snapshot_sha256': project['snapshot_sha256'], 'image_id': IMAGE_ID,
                'project': project['id'], 'arch': arch, 'isa_mode': isa, 'target_triple': triple,
                'compiler_family': family, 'compiler_sha256': tools[driver_name]['sha256'],
                'compile_argv': [x.replace(str(out), 'BUILD') for x in compile_args],
                'link_argv': [x.replace(str(out), 'BUILD') for x in link_args], 'environment': ENV}
    build_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    record = {'schema_version':'cross-isa-0.1', 'build_id': build_id,
              'project':project['id'], 'language':project['language'], 'source':project,
              'target':{'os':'linux', 'format':'elf', 'arch':arch, 'triple':triple,
                        'abi':triple, 'isa_mode':isa, 'machine_flags':machine_flags},
              'toolchain':{'family':family, 'driver':tools[driver_name],
                           'linker':tools['ld.lld'] if family == 'clang' and 'LTO' in profile else tools[triple+'-ld'],
                           'image_id':IMAGE_ID, 'environment_record':'environment.json'},
              'profile':profile, 'optimization_flags':flag, 'attempt':attempt,
              'commands':[], 'status':'success', 'qualified':False, 'eval_ready':{},
              'execution_tests':'not-run', 'split_group':project['repository_url'],
              'capture_policy':{'driver_argv':'complete', 'child_argv_trace':'execve-strace',
                                'source_network':'disabled', 'source_files':'read-only'},
              'collector_sha256':sha(__file__)}
    try:
        for n, cmd in enumerate((compile_args, link_args)):
            r = run(out, n, cmd, cwd=INPUT / 'sources' / project['id'], trace=True)
            record['commands'].append(r)
            if r['returncode'] != 0:
                raise RuntimeError(f'compile/link command {n} failed with status {r["returncode"]}')
        binary = out / 'binary.unstripped.so'
        head = binary.read_bytes()[:64]
        if head[:4] != b'\x7fELF' or head[5] != 1:
            raise ValueError('Expected little-endian ELF')
        machine = struct.unpack_from('<H', head, 18)[0]
        if machine != {'armv7':40, 'riscv64':243}[arch] or head[4] != {'armv7':1, 'riscv64':2}[arch]:
            raise ValueError('ELF architecture/bitness mismatch')
        record['observed_binary'] = {'format':'elf', 'arch':arch, 'bits':32 if arch=='armv7' else 64,
                                     'endianness':'little', 'e_machine':machine}
        objcopy = '/usr/bin/' + triple + '-objcopy'
        commands = [[objcopy, '--only-keep-debug', binary, out/'binary.debug'],
                    [objcopy, '--strip-debug', '--strip-unneeded', binary, out/'binary.stripped.so'],
                    [objcopy, '--add-gnu-debuglink=binary.debug', 'binary.stripped.so'],
                    [objcopy, '--dump-section', '.gnu_debuglink=debuglink.bin', 'binary.stripped.so'],
                    [objcopy, '--dump-section', '.text=original.text', 'binary.unstripped.so'],
                    [objcopy, '--dump-section', '.text=stripped.text', 'binary.stripped.so'],
                    [triple+'-readelf', '-aW', binary], [triple+'-readelf', '-AW', binary],
                    [triple+'-readelf', '--debug-dump=info', out/'binary.debug']]
        for n, cmd in enumerate(commands, 2):
            r = run(out, n, cmd, cwd=out)
            record['commands'].append(r)
            if r['returncode'] != 0:
                raise RuntimeError(f'debug/binary evidence command {n} failed')
        debuglink = (out/'debuglink.bin').read_bytes()
        end = debuglink.index(b'\0'); crcpos = (end + 4) & ~3
        declared_crc = struct.unpack_from('<I', debuglink, crcpos)[0]
        actual_crc = zlib.crc32((out/'binary.debug').read_bytes()) & 0xffffffff
        if debuglink[:end] != b'binary.debug' or declared_crc != actual_crc:
            raise ValueError('ELF debuglink CRC mismatch')
        if sha(out/'original.text') != sha(out/'stripped.text'):
            raise ValueError('Stripping changed .text')
        record['debug_relation'] = {'method':'gnu_debuglink_crc32', 'status':'matched',
                                    'debuglink_crc32':f'{actual_crc:08x}', 'stripped_text_sha256':sha(out/'stripped.text'),
                                    'semantic_mapping_qualified':False}
        for temp in ('debuglink.bin', 'original.text', 'stripped.text'):
            (out/temp).unlink()
    except Exception as exc:
        record['status'] = 'failed'
        record['error'] = str(exc)
    record['artifacts'] = [{'path':p.relative_to(OUT/cell).as_posix(), 'sha256':sha(p), 'size':p.stat().st_size}
                           for p in sorted(out.iterdir()) if p.is_file()]
    (out/'manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    print(cell, project['id'], profile, attempt, record['status'], record.get('error',''), flush=True)
    return record

jobs = [(p, cell, family, profile, attempt) for p in SOURCES for cell in CELLS
        for family in ('gcc', 'clang') for profile in PROFILES
        if family == 'clang' or profile != 'O2-ThinLTO' for attempt in (1, 2)]
if os.environ.get('CORPUS_SMOKE') == '1':
    jobs = jobs[:1]
with ThreadPoolExecutor(max_workers=3) as executor:
    results = list(executor.map(compile_one, jobs))
for cell in sorted({f'{r["target"]["arch"]}-{r["target"]["isa_mode"]}-{r["toolchain"]["family"]}' for r in results}):
    cdir = OUT / cell
    (cdir/'sources').mkdir()
    for source in SOURCES:
        shutil.copyfile(INPUT/'archives'/(source['id']+'.tar'), cdir/source['snapshot_path'])
    selected = [r for r in results if f'{r["target"]["arch"]}-{r["target"]["isa_mode"]}-{r["toolchain"]["family"]}' == cell]
    (cdir/'attempts.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in selected))
(OUT/'summary.json').write_text(json.dumps({'attempts':len(results),
    'successes':sum(r['status']=='success' for r in results),
    'failures':sum(r['status']=='failed' for r in results), 'qualified':0,
    'image_id':IMAGE_ID}, indent=2)+'\n')
