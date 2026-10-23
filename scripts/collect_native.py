"""Pinned direct-TU corpus builds on disposable Windows/macOS/Linux workers.

This collector only invokes trusted compiler/binutils commands, never upstream
build scripts or output programs. Its native record version is separate from the
Docker pilot schema: host/target/debug evidence must not be conflated.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
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


def native_commands(system, arch, compiler, project, profile, source, out):
    src = source / project['source_file']
    if system == 'windows':
        # /Z7 embeds compile debug into .obj; linker /DEBUG creates the distinct PDB.
        compile_argv = [compiler, '/nologo', '/c', '/Z7', '/Od' if profile == 'O0' else '/O2',
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
    p.add_argument('--profiles', nargs='+', choices=['O0','O2','O3','Os'], default=['O0','O2'])
    args = p.parse_args()
    system = {'Darwin':'macos','Windows':'windows','Linux':'linux'}[platform.system()]
    if system == 'windows' and any(x not in ('O0','O2') for x in args.profiles):
        raise ValueError('MSVC adapter currently supports only O0/O2; unsupported profiles cannot be remapped')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(args.config.read_text())
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
    for project in cfg['projects']:
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
        name = 'cl' if system == 'windows' else ('clang++' if project['language']=='cpp' else 'clang')
        executable = Path(shutil.which(name)).resolve()
        toolchain = {'driver':str(executable),'sha256':sha(executable),
                     'version':run([executable,'/Bv' if system=='windows' else '--version'])}
        companion = ['link','dumpbin'] if system=='windows' else ['ld','dsymutil','strip','dwarfdump','otool'] if system=='macos' else ['ld','objcopy','readelf']
        toolchain['companions'] = {n:{'executable':shutil.which(n),'sha256':sha(shutil.which(n))} for n in companion if shutil.which(n)}
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
                    for argv in native_commands(system,args.arch,str(executable),project,profile,source,folder):
                        r=run(argv,cwd=source); record['commands'].append(r)
                        if r['returncode']: raise RuntimeError('Compiler/linker failed')
                    binary=folder/('binary.dll' if system=='windows' else 'binary.dylib' if system=='macos' else 'binary.so')
                    actual=observed_binary(binary)
                    if actual['arch']!=args.arch or actual['format']!=record['target']['format']:
                        raise ValueError('Observed binary target mismatch')
                    record['observed_binary']=actual
                    if system=='windows':
                        if not (folder/'binary.pdb').is_file(): raise ValueError('Missing PDB')
                        record['debug_relation_status']='pdb-present-codeview-raw-unqualified'
                        record['commands'].append(run(['dumpbin','/ALL',binary]))
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
