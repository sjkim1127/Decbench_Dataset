"""Build original macOS zlib/fmt CMake products without executing them."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile

ROOT=Path(__file__).resolve().parents[1]
PROFILES={'O0':['-O0'],'O1':['-O1'],'O2':['-O2'],'O3':['-O3'],'Os':['-Os'],'Oz':['-Oz'],
          'O2-noinline':['-O2','-fno-inline'],'O2-LTO':['-O2','-flto'],'O2-ThinLTO':['-O2','-flto=thin']}
SANDBOX=['/usr/bin/sandbox-exec','-p','(version 1)(allow default)(deny network*)']

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()

def run(argv,cwd=None,env=None):
    p=subprocess.run([str(x) for x in argv],cwd=cwd,env=env,capture_output=True,timeout=2400)
    return {'argv':[str(x) for x in argv],'cwd':str(cwd or Path.cwd()),'returncode':p.returncode,
            'stdout':p.stdout.decode('utf8','replace'),'stderr':p.stderr.decode('utf8','replace')}

def checked(argv,**kwargs):
    r=run(argv,**kwargs)
    if r['returncode']:raise RuntimeError(json.dumps(r))
    return r

def main():
    p=argparse.ArgumentParser();p.add_argument('--arch',choices=['aarch64','x86_64'],required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if platform.system()!='Darwin':raise ValueError('Requires native macOS build tools')
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    environment={k:v for k,v in os.environ.items() if k in ('PATH','SDKROOT','DEVELOPER_DIR','MACOSX_DEPLOYMENT_TARGET','LANG','LC_ALL','SOURCE_DATE_EPOCH')}
    host={'system':platform.platform(),'machine':platform.machine(),'runner_image':os.environ.get('ImageOS'),
          'runner_image_version':os.environ.get('ImageVersion'),'workflow_run':os.environ.get('GITHUB_RUN_ID'),
          'workflow_sha':os.environ.get('GITHUB_SHA'),'sdk_version':run(['xcrun','--show-sdk-version']),
          'xcode':run(['xcodebuild','-version']),'os_build':run(['sw_vers'])}
    rows=[]
    for project in json.loads((ROOT/'configs/macos-whole-projects.json').read_text())['projects']:
        source=out/'sources'/project['id'];source.parent.mkdir(exist_ok=True)
        checked(['git','clone','--no-checkout',project['repository_url'],source])
        checked(['git','-C',source,'checkout','--detach',project['commit_sha']])
        commit=checked(['git','-C',source,'rev-parse','HEAD'])['stdout'].strip()
        tree=checked(['git','-C',source,'rev-parse','HEAD^{tree}'])['stdout'].strip()
        blob=subprocess.run(['git','-C',str(source),'show',commit+':'+project['license_file']],capture_output=True,check=True).stdout
        if commit!=project['commit_sha'] or hashlib.sha256(blob).hexdigest()!=project['license_sha256'] or checked(['git','-C',source,'status','--porcelain'])['stdout'].strip():
            raise ValueError('Pinned upstream source/license mismatch')
        snapshot=out/'sources'/f'{project["id"]}.tar'
        checked(['git','-C',source,'archive','--format=tar','--output='+str(snapshot),commit])
        srcinfo={**project,'tree_hash':tree,'snapshot_path':snapshot.relative_to(out).as_posix(),'snapshot_sha256':sha(snapshot)}
        driver=Path(shutil.which('clang++' if project['language']=='cpp' else 'clang')).resolve()
        toolchain={'family':'clang','driver':str(driver),'sha256':sha(driver),'version':run([driver,'--version']),
                   'companions':{n:{'executable':shutil.which(n),'sha256':sha(Path(shutil.which(n)).resolve()),
                                     'version':run([shutil.which(n),'--version'])}
                                 for n in ('cmake','ninja','dsymutil','dwarfdump','strip') if shutil.which(n)}}
        for profile,flags in PROFILES.items():
            attempts=[]
            for attempt in (1,2):
                folder=out/'builds'/project['id']/profile/str(attempt);folder.mkdir(parents=True)
                record={'schema_version':'native-0.3.0','project':project['id'],'language':project['language'],
                        'source':srcinfo,'target':{'os':'macos','format':'macho','arch':args.arch,'abi':'darwin'},
                        'profile':profile,'attempt':attempt,'host':host,'toolchain':toolchain,'environment':environment,
                        'commands':[],'status':'success','qualified':False,'eval_ready':{},'split_group':project['repository_url'],
                        'execution_tests':'not-run','network_isolation':'macos-sandbox-exec-deny-network',
                        'build_scope':'whole-project-multi-translation-unit','collector_sha256':sha(__file__)}
                def execute(argv):
                    result=run(SANDBOX+[str(x) for x in argv],cwd=source,env=environment)
                    n=len(record['commands']);(folder/f'command-{n}.stdout').write_text(result.pop('stdout'))
                    (folder/f'command-{n}.stderr').write_text(result.pop('stderr'))
                    result.update({'stdout_path':f'command-{n}.stdout','stderr_path':f'command-{n}.stderr'});record['commands'].append(result)
                    if result['returncode']:raise RuntimeError(f'command {n} failed')
                try:
                    build=folder/'cmake-build';cflags=' '.join(flags+['-g','-DNDEBUG'])
                    config=['cmake','-S',source,'-B',build,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',
                            '-DCMAKE_OSX_ARCHITECTURES='+('arm64' if args.arch=='aarch64' else 'x86_64'),
                            '-DCMAKE_C_FLAGS_RELEASE='+cflags,'-DCMAKE_CXX_FLAGS_RELEASE='+cflags,
                            '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON','-DBUILD_SHARED_LIBS=ON',
                            '-DCMAKE_SHARED_LINKER_FLAGS='+' '.join(x for x in flags if x.startswith('-flto'))]
                    if project['id']=='zlib':config+=['-DZLIB_BUILD_TESTING=OFF','-DZLIB_BUILD_STATIC=OFF','-DZLIB_INSTALL=OFF']
                    else:config+=['-DFMT_TEST=OFF','-DFMT_DOC=OFF','-DFMT_INSTALL=OFF']
                    execute(config);execute(['cmake','--build',build,'--parallel','2','--verbose'])
                    prefix='libz.' if project['id']=='zlib' else 'libfmt.'
                    products=[x for x in build.rglob('*.dylib') if x.name.startswith(prefix) and x.is_file() and not x.is_symlink()]
                    if len(products)!=1:raise ValueError('Expected one upstream shared library: '+str(products))
                    shutil.copyfile(products[0],folder/'binary.dylib')
                    from collect_native import observed_binary
                    observed=observed_binary(folder/'binary.dylib')
                    if observed!={'format':'macho','arch':args.arch}:raise ValueError('Wrong Mach-O target')
                    record['observed_binary']=observed
                    execute(['dsymutil',folder/'binary.dylib','-o',folder/'binary.dSYM'])
                    ids=[re.findall(r'UUID: ([A-Fa-f0-9-]+)',run(['dwarfdump','--uuid',x])['stdout']) for x in (folder/'binary.dylib',folder/'binary.dSYM')]
                    if not ids[0] or ids[0]!=ids[1]:raise ValueError('dSYM UUID mismatch')
                    record['debug_relation_status']='uuid-matched';record['debug_uuid']=ids[0]
                    execute(['strip','-S','-x','-o',folder/'binary.stripped.dylib',folder/'binary.dylib'])
                    stripped_ids=re.findall(r'UUID: ([A-Fa-f0-9-]+)',run(['dwarfdump','--uuid',folder/'binary.stripped.dylib'])['stdout'])
                    if ids[0]!=stripped_ids:raise ValueError('Stripped UUID mismatch')
                    record['stripped_uuid_matches']=True
                    if checked(['git','-C',source,'status','--porcelain'])['stdout'].strip():raise ValueError('Upstream worktree changed')
                    compile_commands=json.loads((build/'compile_commands.json').read_text())
                    record['translation_units']=len({x['file'] for x in compile_commands})
                    if record['translation_units']<2:raise ValueError('Expected genuine multi-TU project')
                    shutil.copyfile(build/'compile_commands.json',folder/'compile_commands.json')
                except Exception as exc:
                    record['status']='failed';record['error']=str(exc)
                build=folder/'cmake-build'
                if build.exists():
                    archive=folder/'cmake-build.tar.gz'
                    with tarfile.open(archive,'w:gz',compresslevel=2) as tf:tf.add(build,arcname='cmake-build')
                    shutil.rmtree(build)
                record['artifacts']=[{'path':f.relative_to(out).as_posix(),'sha256':sha(f),'size':f.stat().st_size}
                                     for f in sorted(folder.rglob('*')) if f.is_file()]
                (folder/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
                with (out/'attempts.jsonl').open('a') as ledger:ledger.write(json.dumps(record)+'\n')
                attempts.append(record);rows.append(record)
                print(args.arch,project['id'],profile,attempt,record['status'],record.get('error',''),flush=True)
            pairs=[]
            for r in attempts:pairs.append({Path(x['path']).name:x['sha256'] for x in r['artifacts']})
            replay={'project':project['id'],'profile':profile,'attempts':2,'statuses':[r['status'] for r in attempts],
                    'artifact_hash_equal':{k:pairs[0].get(k)==pairs[1].get(k) for k in pairs[0].keys()|pairs[1].keys()}}
            (folder.parent/'replay.json').write_text(json.dumps(replay,indent=2)+'\n')
    print(json.dumps({'attempts':len(rows),'successes':sum(r['status']=='success' for r in rows)}))
    return int(any(r['status']!='success' for r in rows))

if __name__=='__main__':raise SystemExit(main())
