"""Build the original Mint project for macOS x86-64 using frozen dependencies."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
from upstream_sources import acquire,sha,verify_program_sources
from collect_native import observed_binary

ROOT=Path(__file__).resolve().parents[1]
SANDBOX=['/usr/bin/sandbox-exec','-p','(version 1)(allow default)(deny network*)']


def run(argv,*,cwd=None,env=None):
    p=subprocess.run([str(x) for x in argv],cwd=cwd,env=env,capture_output=True,text=True,timeout=3600)
    return {'argv':[str(x) for x in argv],'cwd':str(cwd or Path.cwd()),'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}


def archive_tree(source,dest,name):
    with tarfile.open(dest,'w') as tf:
        tf.add(source,arcname=name,filter=lambda info:None if '.git' in Path(info.name).parts else info)


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--seed',type=Path,required=True);args=p.parse_args()
    args.language='swift'
    root=args.output.resolve();root.mkdir(parents=True,exist_ok=False)
    (root/'tooling').mkdir()
    for name in ('collect_swift_macos_x64.py','upstream_sources.py','collect_native.py'):shutil.copyfile(ROOT/'scripts'/name,root/'tooling'/name)
    project=next(x for x in json.loads((ROOT/'configs/additional-language-projects.json').read_text())['projects'] if x['language']==args.language)
    seed=args.seed.resolve();source=root/'source'
    shutil.copytree(seed/'source',source,symlinks=True)
    shutil.copyfile(seed/'source.tar',root/'source.tar')
    shutil.copyfile(seed/'source-provenance.json',root/'source-provenance.json')
    provenance=json.loads((root/'source-provenance.json').read_text())
    if provenance['commit_sha']!=project['commit_sha'] or provenance['license_sha256']!=project['license_sha256'] or sha(root/'source.tar')!=provenance['source_snapshot_sha256']:
        raise ValueError('Frozen original upstream source identity mismatch')
    verify_program_sources(source,provenance)
    home=root/'home';home.mkdir();env={k:v for k,v in os.environ.items() if k in ('PATH','TMPDIR','DEVELOPER_DIR','SDKROOT')};env['HOME']=str(home)
    env.update({'LC_ALL':'C','TZ':'UTC','SOURCE_DATE_EPOCH':'0'})
    tools={}
    for name in ((['swift','swiftc','clang','dsymutil','strip','dwarfdump']) if args.language=='swift' else ['zig','llvm-objcopy','dsymutil','strip','dwarfdump']):
        path=shutil.which(name)
        if path:tools[name]={'path':path,'resolved_sha256':sha(Path(path).resolve()),'version':run([path,'version' if name=='zig' else '--version'],env=env)}
    host={'os':run(['sw_vers']), 'sdk':run(['xcrun','--show-sdk-path']), 'sdk_version':run(['xcrun','--show-sdk-version']),
          'xcode':run(['xcodebuild','-version']), 'architecture':os.uname().machine}
    prepare=root/'prepare';shutil.copytree(seed/'prepare',prepare,symlinks=True)
    if args.language=='swift':
        common=['--package-path',source,'--cache-path',prepare/'cache','--config-path',prepare/'config','--security-path',prepare/'security']
        checkouts=prepare/'scratch/checkouts'
        dependencies=json.loads((prepare/'dependency-commits.json').read_text())
        observed={p.name:run(['git','-C',p,'rev-parse','HEAD'])['stdout'].strip() for p in checkouts.iterdir() if p.is_dir()}
        if observed != dependencies:raise ValueError('Frozen dependency commits changed')
        if sha(source/'Package.resolved')!=sha(prepare/'Package.resolved'):
            raise ValueError('Swift package resolution pin changed')
        variants=[(profile,'x86_64-apple-macosx13.0') for profile in ('debug','release')]
    else:
        env['ZIG_GLOBAL_CACHE_DIR']=str(prepare/'global-cache')
        prep=run(['zig','build','--fetch'],cwd=source,env=env)
        (prepare/'fetch.json').write_text(json.dumps(prep,indent=2)+'\n')
        if prep['returncode']:raise RuntimeError('Zig upstream dependency acquisition failed: '+prep['stderr'][-2000:])
        archive_tree(prepare/'global-cache/p',prepare/'dependency-sources.tar','p')
        (prepare/'zig-env.json').write_text(json.dumps(run(['zig','env'],env=env),indent=2)+'\n')
        variants=[(profile,target) for target in ('aarch64-macos','aarch64-linux-gnu','x86_64-windows-gnu') for profile in ('Debug','ReleaseSafe')]
    rows=[]
    for profile,target in variants:
        for attempt in (1,2):
            out=root/'builds'/target/profile/str(attempt);out.mkdir(parents=True)
            build_env=dict(env);build_env['CLANG_MODULE_CACHE_PATH']=str(out/'module-cache')
            record={'schema_version':'opensource-0.1.0','language':args.language,'project':project['repository'],
                    'source':provenance,'profile':profile,'attempt':attempt,'target':{'triple':target},
                    'tools':tools,'host':host,'environment':build_env,'commands':[],'status':'success',
                    'network_during_build':False,'network_isolation':'macos-sandbox-exec-deny-network',
                    'qualified':False,'eval_ready':{},'source_origin':'upstream-open-source',
                    'dataset_authored_program_source':False,'collector_supplied_harness':False,
                    'final_program_execution':False,'build_tools_execution':'upstream-package-manifests-and-code-generators-only'}
            def execute(argv,*,offline=True):
                result=run((SANDBOX if offline else [])+argv,cwd=source,env=build_env)
                name='command-'+str(len(record['commands']));(out/(name+'.stdout')).write_text(result.pop('stdout'));(out/(name+'.stderr')).write_text(result.pop('stderr'))
                result.update({'stdout_path':name+'.stdout','stderr_path':name+'.stderr'});record['commands'].append(result)
                if result['returncode']:raise RuntimeError(name+' failed')
            try:
                if args.language=='swift':
                    shutil.copytree(prepare/'scratch',out/'scratch',symlinks=True)
                    execute(['swift','build',*common,'--scratch-path',out/'scratch','--disable-automatic-resolution','--skip-update','--disable-sandbox',
                             '--configuration',profile,'--product','mint','--triple',target,'--jobs','2','--verbose','-Xswiftc','-g'])
                    products=[f for f in (out/'scratch').rglob('mint') if f.is_file() and f.parent.name==profile]
                    if len(products)!=1:raise ValueError('Expected one real upstream Mint product: '+str(products))
                    shutil.copyfile(products[0],out/'binary.unstripped')
                    record['dependency_pins_sha256']=sha(prepare/'Package.resolved')
                else:
                    build_env['ZIG_GLOBAL_CACHE_DIR']=str(out/'global-cache');(out/'global-cache').mkdir()
                    shutil.copytree(prepare/'global-cache/p',out/'global-cache/p')
                    execute(['zig','build','-Dtarget='+target,'-Doptimize='+profile,'-Dstrip=false','--prefix',out/'install',
                             '--cache-dir',out/'local-cache','--global-cache-dir',out/'global-cache','-j2','--verbose'])
                    product=out/'install/bin'/('zls.exe' if 'windows' in target else 'zls')
                    if not product.is_file():raise ValueError('Missing original upstream ZLS product')
                    shutil.copyfile(product,out/'binary.unstripped')
                    for file in (out/'install').rglob('*.pdb'):shutil.copyfile(file,out/file.name)
                actual=observed_binary(out/'binary.unstripped');record['target'].update(actual)
                record['target']['os']={'elf':'linux','pe':'windows','macho':'macos'}[actual['format']]
                record['source_integrity']=verify_program_sources(source,provenance)
                if actual['format']=='macho':
                    execute(['dsymutil',out/'binary.unstripped','-o',out/'binary.dSYM'])
                    uuids=[run(['dwarfdump','--uuid',p]) for p in (out/'binary.unstripped',out/'binary.dSYM')]
                    ids=[re.findall(r'UUID: ([A-Fa-f0-9-]+)',x['stdout']) for x in uuids]
                    record['uuid_evidence']=uuids
                    if not ids[0] or ids[0]!=ids[1]:raise ValueError('Binary/dSYM UUID mismatch')
                    execute(['strip','-S','-x','-o',out/'binary.stripped',out/'binary.unstripped'])
                else:
                    if actual['format']=='elf':
                        execute(['llvm-objcopy','--only-keep-debug',out/'binary.unstripped',out/'binary.debug'])
                    execute(['llvm-objcopy','--strip-debug',out/'binary.unstripped',out/'binary.stripped'])
            except Exception as exc:record['status']='failed';record['error']=str(exc)
            artifacts=[p for p in out.iterdir() if p.is_file()]
            if (out/'binary.dSYM').exists():
                archive_tree(out/'binary.dSYM',out/'binary.dSYM.tar','binary.dSYM');artifacts.append(out/'binary.dSYM.tar')
            record['artifacts']=[{'path':f.relative_to(root).as_posix(),'sha256':sha(f),'size':f.stat().st_size} for f in sorted(artifacts)]
            (out/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');rows.append(record)
            print(args.language+' '+target+' '+profile+' attempt '+str(attempt)+': '+record['status'],flush=True)
    (root/'attempts.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    return int(any(r['status']!='success' for r in rows))


if __name__=='__main__':raise SystemExit(main())
