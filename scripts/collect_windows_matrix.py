"""Pinned direct-TU MSVC/clang-cl matrix on disposable Windows workers.

This collector only invokes trusted compiler/binutils commands, never upstream
build scripts or output programs. Its native record version is separate from the
Docker pilot schema: host/target/debug evidence must not be conflated.
"""
import argparse
import hashlib
import json
import ntpath
import os
from pathlib import Path, PureWindowsPath
import platform
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
import time

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(argv, cwd=None, timeout=1200):
    proc = subprocess.run([str(a) for a in argv], cwd=cwd, capture_output=True, timeout=timeout)
    return {'argv': [str(a) for a in argv], 'cwd': str(cwd or Path.cwd()),
            'returncode': proc.returncode, 'stdout': proc.stdout.decode('utf-8', 'replace'),
            'stderr': proc.stderr.decode('utf-8', 'replace')}


def checked(argv, **kw):
    result = run(argv, **kw)
    if result['returncode']:
        raise RuntimeError(json.dumps(result))
    return result


def native_commands(system, arch, compiler, project, profile, source, out, family='msvc'):
    src = source / project['source_file']
    if system == 'windows':
        # /Z7 embeds compile debug into .obj; linker /DEBUG creates the distinct PDB.
        if family == 'msvc':
            options = {'O0':['/Od'], 'O2':['/O2'], 'Osize-msvc':['/O1'],
                       'O2-noinline':['/O2','/Ob0']}[profile]
            target = []
        else:
            flags = {'O0':['-O0'], 'O1':['-O1'], 'O2':['-O2'], 'O3':['-O3'],
                     'Os':['-Os'], 'Oz':['-Oz'], 'O2-noinline':['-O2','-fno-inline']}[profile]
            options = ['/clang:' + x for x in flags]
            target = ['--target=' + {'x86':'i686-pc-windows-msvc',
                                    'x86_64':'x86_64-pc-windows-msvc',
                                    'aarch64':'aarch64-pc-windows-msvc'}[arch]]
        compile_argv = [compiler, *target, '/nologo', '/c', '/Z7', *options,
                        '/EHsc', '/MD', '/Fo' + str(out / 'unit.obj'), str(src)]
        if project['language'] == 'cpp':
            compile_argv += ['/std:c++14']
        return [compile_argv, ['link', '/DLL', '/NOLOGO', '/DEBUG:FULL', '/INCREMENTAL:NO',
                 '/OPT:NOREF', '/OPT:NOICF', '/MACHINE:' + {'x86_64':'X64','x86':'X86','aarch64':'ARM64'}[arch],
                 '/OUT:' + str(out / 'binary.dll'), '/PDB:' + str(out / 'binary.pdb'), str(out / 'unit.obj')]]
    flags = ['-std=' + project['standard'], '-' + profile, '-g', '-fPIC', '-v']
    if system == 'macos':
        flags += ['-arch', {'x86_64':'x86_64', 'aarch64':'arm64'}[arch]]
    return [[compiler, *flags, '-c', str(src), '-o', str(out / 'unit.o')],
            [compiler, '-v', '-dynamiclib' if system == 'macos' else '-shared',
             *(['-arch', {'x86_64':'x86_64','aarch64':'arm64'}[arch]] if system == 'macos' else []),
             str(out / 'unit.o'), '-o', str(out / ('binary.dylib' if system == 'macos' else 'binary.so'))]]


_LINE_MARKER = re.compile(r'^\s*#\s*(?:line\s+)?\d+\s+"((?:\\.|[^"\\])*)"')


def project_source_projection(data, source):
    """Retain only preprocessed project source and the line markers."""
    root = PureWindowsPath(ntpath.normpath(str(source)))
    output = []
    inside = False
    project_lines = 0
    for line in data.decode('utf-8-sig', 'surrogateescape').splitlines():
        marker = _LINE_MARKER.match(line)
        if marker:
            spelling = re.sub(r'\\([\\"])', r'\1', marker[1])
            path = PureWindowsPath(ntpath.normpath(ntpath.join(str(root), spelling)))
            inside = not spelling.startswith('<') and path.is_relative_to(root)
            output.append(line)
        elif inside:
            output.append(line)
            project_lines += bool(line.strip())
        else:
            output.append('')
    if not project_lines:
        raise ValueError('Preprocessed TU has no project source with line markers')
    return ('\n'.join(output) + '\n').encode('utf-8', 'surrogateescape'), project_lines


def capture_cpp_tu(compile_argv, source, source_file, folder, record):
    """Capture the original preprocessor input and compile its exact bytes."""
    original_source = str(source / source_file)
    object_option = '/Fo' + str(folder / 'unit.obj')
    if compile_argv.count(original_source) != 1 or compile_argv.count(object_option) != 1:
        raise ValueError('Unexpected native compile command')
    with TemporaryDirectory(prefix='decbench-cpp-tu-') as temporary:
        raw = Path(temporary) / 'unit.ii'
        preprocess = [arg for arg in compile_argv if arg not in ('/c', object_option)]
        preprocess += ['/P', '/Fi' + str(raw)]
        result = run(preprocess, cwd=source)
        record['commands'].append(result)
        if result['returncode'] or not raw.is_file():
            raise ValueError('C++ preprocessing failed')
        data = raw.read_bytes()
        projection, project_lines = project_source_projection(data, source)
        replay = ['/Fo' + str(folder / 'unit.replayed.obj') if arg == object_option else arg
                  for arg in compile_argv]
        source_path = Path(original_source)
        original_bytes = source_path.read_bytes()
        original_stat = source_path.stat()
        # Both compilers derive some private symbols from the primary input path.
        # Replay inside this disposable checkout and restore the source after it.
        try:
            source_path.write_bytes(data)
            result = run(replay, cwd=source)
        finally:
            source_path.write_bytes(original_bytes)
            os.utime(source_path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        record['commands'].append(result)
        if result['returncode'] or not (folder / 'unit.replayed.obj').is_file():
            raise ValueError('C++ preprocessed replay failed')
        projected = folder / 'project.ii'
        projected.write_bytes(projection)
        record['cpp_preprocessing'] = {
            'raw_sha256': hashlib.sha256(data).hexdigest(),
            'raw_size': len(data),
            'source_member_sha256': hashlib.sha256(original_bytes).hexdigest(),
            'replay_input_path': original_source,
            'project_projection': projected.name,
            'project_projection_sha256': sha(projected),
            'project_projection_lines': project_lines,
            'replayed_object': 'unit.replayed.obj',
        }


def observed_binary(path):
    import struct
    b = path.read_bytes()
    if b[:2] == b'MZ':
        offset = struct.unpack_from('<I', b, 0x3c)[0]
        if b[offset:offset+4] != b'PE\0\0':
            raise ValueError('Invalid PE signature')
        machine = struct.unpack_from('<H', b, offset+4)[0]
        return {'format':'pe', 'arch':{0x8664:'x86_64',0x14c:'x86',0xaa64:'aarch64'}[machine]}
    if b[:4] == b'\xcf\xfa\xed\xfe':
        cpu = struct.unpack_from('<I', b, 4)[0]
        return {'format':'macho','arch':{0x1000007:'x86_64',0x100000c:'aarch64'}[cpu]}
    if b[:4] == b'\x7fELF':
        machine = struct.unpack_from('<H' if b[5] == 1 else '>H', b, 18)[0]
        return {'format':'elf','arch':{62:'x86_64',3:'x86',183:'aarch64',40:'armv7'}[machine]}
    raise ValueError('Unsupported binary header')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--arch', required=True, choices=['x86_64','x86','aarch64'])
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--config', type=Path, default=ROOT/'configs/native-projects.json')
    p.add_argument('--profiles', nargs='+', choices=['O0','O1','O2','O3','Os','Oz','O2-noinline','Osize-msvc'], default=['O0','O2'])
    p.add_argument('--family', choices=['msvc','clang-cl'], default='msvc')
    p.add_argument('--projects', nargs='+')
    p.add_argument('--capture-cpp-tu', action='store_true')
    args = p.parse_args()
    system = {'Darwin':'macos','Windows':'windows','Linux':'linux'}[platform.system()]
    if system == 'windows':
        supported = {'O0','O2','Osize-msvc','O2-noinline'} if args.family == 'msvc' else {'O0','O1','O2','O3','Os','Oz','O2-noinline'}
        if any(x not in supported for x in args.profiles):
            raise ValueError('Unsupported compiler profile; MSVC /O1 is named Osize-msvc')
    elif any(x in ('O2-noinline','Osize-msvc') for x in args.profiles):
        raise ValueError('Windows-only profile for this native collector')
    if args.capture_cpp_tu and system != 'windows':
        p.error('--capture-cpp-tu requires the Windows compiler matrix')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(args.config.read_text())
    projects = cfg['projects']
    if args.projects:
        unknown = set(args.projects) - {project['id'] for project in projects}
        if unknown:
            p.error('Unknown projects: ' + ', '.join(sorted(unknown)))
        projects = [project for project in projects if project['id'] in args.projects]
    ledger = out/'attempts.jsonl'
    failures = 0
    # Explicit allowlist: do not dump full hosted-runner environments/credentials.
    environment = {k: v for k,v in os.environ.items() if k in {
        'PATH','INCLUDE','LIB','LIBPATH','CL','_CL_','LINK','_LINK_','SDKROOT',
        'MACOSX_DEPLOYMENT_TARGET','VCToolsVersion','WindowsSDKVersion','VSCMD_ARG_TGT_ARCH',
        'CC','CXX','CFLAGS','CXXFLAGS','LDFLAGS','LANG','LC_ALL','SOURCE_DATE_EPOCH'}}
    host = {'system':platform.platform(), 'machine':platform.machine(),
            'runner_image':os.environ.get('ImageOS'), 'runner_image_version':os.environ.get('ImageVersion'),
            'runner_arch':os.environ.get('RUNNER_ARCH'), 'workflow_run':os.environ.get('GITHUB_RUN_ID'),
            'workflow_sha':os.environ.get('GITHUB_SHA')}
    if system == 'macos':
        host['sdk'] = run(['xcrun','--show-sdk-path'])
        host['sdk_version'] = run(['xcrun','--show-sdk-version'])
        host['xcode'] = run(['xcodebuild','-version'])
        host['os_build'] = run(['sw_vers'])
    for project in projects:
        source = out/'sources'/project['id']
        source.parent.mkdir(exist_ok=True)
        if not source.exists():
            checked(['git','clone','--no-checkout',project['repository_url'],source])
        checked(['git','-C',source,'-c','core.autocrlf=false','-c','core.eol=lf','checkout','--detach',project['commit_sha']])
        commit = checked(['git','-C',source,'rev-parse','HEAD'])['stdout'].strip()
        tree = checked(['git','-C',source,'rev-parse','HEAD^{tree}'])['stdout'].strip()
        if commit != project['commit_sha'] or checked(['git','-C',source,'status','--porcelain'])['stdout'].strip():
            raise ValueError('Source identity/cleanliness check failed')
        # Review the canonical Git blob; Windows checkout EOL conversion is a
        # workspace property and must not be mistaken for an upstream license edit.
        license_blob = subprocess.run(['git','-C',str(source),'show',commit+':'+project['license_file']],
                                      capture_output=True,check=True,timeout=120).stdout
        if hashlib.sha256(license_blob).hexdigest() != project['license_sha256']:
            raise ValueError('Reviewed license content changed')
        license_worktree_sha256 = sha(source/project['license_file'])
        snapshot = out/'sources'/(project['id']+'.tar')
        checked(['git','-C',source,'archive','--format=tar','--output='+str(snapshot),'HEAD'])
        name = ('cl' if args.family == 'msvc' else 'clang-cl') if system == 'windows' else ('clang++' if project['language']=='cpp' else 'clang')
        executable = Path(shutil.which(name)).resolve()
        toolchain = {'driver':str(executable),'sha256':sha(executable),
                     'family':args.family if system=='windows' else 'clang',
                     'version':run([executable,'/Bv' if system=='windows' and args.family=='msvc' else '--version'])}
        companion = ['link','dumpbin','llvm-objcopy'] if system=='windows' else ['ld','dsymutil','strip','dwarfdump','otool'] if system=='macos' else ['ld','objcopy','readelf']
        toolchain['companions'] = {n:{'executable':shutil.which(n),'sha256':sha(shutil.which(n)),
                                     'version':run([shutil.which(n), '/?' if n in ('link','dumpbin') else '--version'])}
                                   for n in companion if shutil.which(n)}
        for profile in args.profiles:
            attempts=[]
            for attempt in (1,2):
                folder = out/'builds'/project['id']/profile/str(attempt)
                folder.mkdir(parents=True,exist_ok=False)
                record = {'schema_version':'native-0.3.0','project':project['id'],'language':project['language'],
                          'source':{**project,'commit_sha':commit,'tree_hash':tree,'snapshot_path':snapshot.relative_to(out).as_posix(),'snapshot_sha256':sha(snapshot),
                                    'license_worktree_sha256':license_worktree_sha256},
                          'target':{'os':system,'arch':args.arch,'format':{'windows':'pe','macos':'macho','linux':'elf'}[system],
                                    'abi':{'windows':'msvc','macos':'darwin','linux':'sysv'}[system],
                                    'abi_detail_status':'raw-compiler-loader-evidence-only'},
                          'profile':profile,'attempt':attempt,'host':host,'toolchain':toolchain,'environment':environment,
                          'commands':[],'status':'success','qualified':False,'eval_ready':{},'split_group':project['repository_url'],
                          'execution_tests':'not-run','child_argv_trace':'verbose-only','network_isolation':'not-enforced-native-direct-compiler-no-upstream-scripts',
                          'collector_sha256':sha(Path(__file__))}
                try:
                    commands = native_commands(system,args.arch,str(executable),project,profile,source,folder,args.family)
                    for argv in commands:
                        r=run(argv,cwd=source); record['commands'].append(r)
                        if r['returncode']: raise RuntimeError('Compiler/linker failed')
                    if args.capture_cpp_tu and project['language'] == 'cpp':
                        capture_cpp_tu(commands[0], source, project['source_file'], folder, record)
                    binary=folder/('binary.dll' if system=='windows' else 'binary.dylib' if system=='macos' else 'binary.so')
                    actual=observed_binary(binary)
                    if actual['arch']!=args.arch or actual['format']!=record['target']['format']:
                        raise ValueError('Observed binary target mismatch')
                    record['observed_binary']=actual
                    if system=='windows':
                        if not (folder/'binary.pdb').is_file(): raise ValueError('Missing PDB')
                        record['debug_relation_status']='pdb-present-codeview-raw-unqualified'
                        record['commands'].append(run(['dumpbin','/ALL',binary]))
                        # Preserve stripping outcome as evidence; LLVM COFF support depends on version.
                        llvm_objcopy = shutil.which('llvm-objcopy')
                        if llvm_objcopy:
                            stripped=run([llvm_objcopy,'--strip-debug',binary,folder/'binary.stripped.dll'])
                            record['commands'].append(stripped)
                            if stripped['returncode']==0 and (folder/'binary.stripped.dll').is_file():
                                if observed_binary(folder/'binary.stripped.dll') != actual:
                                    raise ValueError('Stripped PE target changed')
                                record['stripping_status']='llvm-objcopy-strip-debug-succeeded-unqualified'
                            else:
                                record['stripping_status']='llvm-objcopy-failed'
                        else:
                            record['stripping_status']='llvm-objcopy-unavailable'
                    elif system=='macos':
                        checked_debug=run(['dsymutil',binary,'-o',folder/'binary.dSYM']); record['commands'].append(checked_debug)
                        if checked_debug['returncode']: raise ValueError('dsymutil failed')
                        uuids=[run(['dwarfdump','--uuid',x]) for x in (binary,folder/'binary.dSYM')]
                        record['commands']+=uuids
                        import re
                        ids=[re.findall(r'UUID: ([A-Fa-f0-9-]+)',x['stdout']) for x in uuids]
                        if not ids[0] or ids[0]!=ids[1]: raise ValueError('dSYM UUID mismatch')
                        record['debug_relation_status']='uuid-matched'
                        record['commands'].append(run(['otool','-l',binary]))
                        stripped=run(['strip','-S','-x','-o',folder/'binary.stripped.dylib',binary]); record['commands'].append(stripped)
                        if stripped['returncode']: raise ValueError('strip failed')
                    else:
                        record['commands'].append(run(['readelf','-aW',binary]))
                    record['artifacts']=[{'path':x.relative_to(out).as_posix(),'sha256':sha(x),'size':x.stat().st_size}
                                         for x in sorted(folder.rglob('*')) if x.is_file()]
                except Exception as exc:
                    record['status']='failed';record['error']=str(exc);failures+=1
                (folder/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
                with ledger.open('a') as f: f.write(json.dumps(record)+'\n')
                attempts.append(record)
                print(f"{system}/{args.arch} {project['id']} {profile} attempt {attempt}: {record['status']}",flush=True)
            comparison={'project':project['id'],'profile':profile,'attempts':2,'statuses':[a['status'] for a in attempts],
                        'artifact_hash_equal':None,'qualified':False}
            if all(a['status']=='success' for a in attempts):
                maps=[{Path(x['path']).relative_to(Path('builds')/project['id']/profile/str(i+1)).as_posix():x['sha256'] for x in a['artifacts']} for i,a in enumerate(attempts)]
                comparison['artifact_hash_equal']={n:maps[0].get(n)==maps[1].get(n) for n in maps[0].keys()|maps[1].keys()}
            (out/'builds'/project['id']/profile/'replay.json').write_text(json.dumps(comparison,indent=2)+'\n')
    print(json.dumps({'failures':failures,'ledger':str(ledger)}))
    return int(failures>0)


if __name__=='__main__':
    raise SystemExit(main())
