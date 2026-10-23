"""Small source-backed clean/garble campaign. Never run corpus executables."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def command(argv, cwd=None, env=None):
    p=subprocess.run([str(x) for x in argv],cwd=cwd,env=env,capture_output=True,timeout=1800)
    return {'argv':[str(x) for x in argv],'cwd':str(cwd or Path.cwd()),'returncode':p.returncode,
            'stdout':p.stdout.decode('utf8','replace'),'stderr':p.stderr.decode('utf8','replace')}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--garble',type=Path,required=True)
    p.add_argument('--publish',action='store_true')
    args=p.parse_args();root=args.output.resolve();root.mkdir(parents=True,exist_ok=False)
    garble=args.garble.resolve();go=Path(shutil.which('go')).resolve()
    source=root/'source'
    repo='https://github.com/BurntSushi/toml.git';commit='d733fc535e4a9f3c454e421a87b90ade5d49bf31'
    checked=[]
    for argv in (['git','clone','--no-checkout',repo,source],['git','-C',source,'checkout','--detach',commit]):
        r=command(argv);checked.append(r)
        if r['returncode']: raise RuntimeError(r['stderr'])
    # Preserve exact upstream MIT terms, including the copyright notice.
    license_text=(source/'COPYING').read_text()
    if 'Permission is hereby granted' not in license_text: raise ValueError('Review license before proceeding')
    archive=root/'source.tar';r=command(['git','-C',source,'archive','--format=tar','--output='+str(archive),'HEAD'])
    if r['returncode']:raise RuntimeError(r['stderr'])
    go_version=command([go,'version']);garble_version=command([garble,'version'])
    if 'v0.15.0' not in garble_version['stdout']:raise ValueError('Expected pinned garble v0.15.0')
    seed='AAECAwQFBgcICQoLDA0ODw=='
    rows=[]
    paths=json.loads(command([go,'env','-json','GOROOT','GOMODCACHE'])['stdout'])
    notices=[]
    for original, name in [(Path(paths['GOROOT'])/'LICENSE','GO-LICENSE'),
                           (Path(paths['GOMODCACHE'])/'mvdan.cc/garble@v0.15.0/LICENSE','GARBLE-LICENSE')]:
        if original.exists():
            shutil.copyfile(original,root/name);notices.append(root/name)
    for os_name,arch in [('linux','amd64'),('windows','amd64'),('darwin','arm64')]:
        env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','TMPDIR','SYSTEMROOT')}
        env.update({'GOOS':os_name,'GOARCH':arch,'CGO_ENABLED':'0','GOTOOLCHAIN':'local',
                    'GOPROXY':'off','GOSUMDB':'off','GOTELEMETRY':'off'})
        for track in ('clean','obfuscated'):
            folder=root/'builds'/(os_name+'-'+arch)/track;folder.mkdir(parents=True)
            binary=folder/('tomlv.exe' if os_name=='windows' else 'tomlv')
            flags=['build','-p=2','-mod=readonly','-trimpath','-x','-o',str(binary),'./cmd/tomlv']
            argv=[go,*flags] if track=='clean' else [garble,'-seed='+seed,'-literals','-debugdir='+str(folder/'transformed-source'),*flags]
            result=command(argv,cwd=source,env=env)
            record={'schema_version':'obfuscation-0.1.0','project':'BurntSushi/toml','language':'go',
                    'repository_url':repo,'commit_sha':commit,'source_snapshot_sha256':sha(archive),
                    'license':{'spdx':'MIT','path':'COPYING','sha256':sha(source/'COPYING')},
                    'target':{'os':'macos' if os_name=='darwin' else os_name,'goos':os_name,'goarch':arch,
                              'arch':'x86_64' if arch=='amd64' else 'aarch64','cgo':False},'track':track,
                    'go_environment':command([go,'env','-json','GOOS','GOARCH','GOAMD64','GOARM64','GOVERSION','GOTOOLCHAIN','CGO_ENABLED'],env=env),
                    'go':{'version':go_version,'executable_sha256':sha(go)},
                    'obfuscator':{'version':garble_version,'executable_sha256':sha(garble),
                                  'repository':'https://github.com/burrowers/garble',
                                  'tag_object_sha':'05caa14fcc5401e350f6babc935d78282eab96af',
                                  'commit_sha':'6dab979d1cae7c703aeff286f1c70319c34a6c35',
                                  'seed':seed,'literals':True} if track=='obfuscated' else None,
                    'command':result,'status':'success' if result['returncode']==0 else 'failed',
                    'qualified':False,'semantic_validation':'not-run','produced_program_execution':False,
                    'debug_mapping_status':'garble-not-qualified' if track=='obfuscated' else 'raw-unqualified',
                    'split_group':repo,'environment':{k:v for k,v in env.items() if k not in ('HOME','TMPDIR')},
                    'collector_sha256':sha(Path(__file__))}
            if binary.exists():
                from collect_native import observed_binary
                record['observed_binary']=observed_binary(binary)
                expected={'linux':'elf','windows':'pe','darwin':'macho'}[os_name]
                if record['observed_binary']!={'format':expected,'arch':'x86_64' if arch=='amd64' else 'aarch64'}:
                    raise ValueError('Wrong observed binary target')
            record['build_id']=hashlib.sha256(json.dumps({k:v for k,v in record.items() if k not in ('command','status')},sort_keys=True).encode()).hexdigest()
            record['artifacts']=[{'path':x.relative_to(root).as_posix(),'sha256':sha(x),'size':x.stat().st_size} for x in sorted(folder.rglob('*')) if x.is_file()]
            (folder/'manifest.json').write_text(json.dumps(record,indent=2)+'\n');rows.append(record)
            print(f"{os_name}/{arch} {track}: {record['status']}",flush=True)
    for row in rows:
        if row['track']=='obfuscated': row['baseline_build_id']=next(x['build_id'] for x in rows if x['track']=='clean' and x['target']==row['target'])
        (root/'builds'/(row['target']['goos']+'-'+row['target']['goarch'])/row['track']/'manifest.json').write_text(json.dumps(row,indent=2)+'\n')
    (root/'builds.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    package=root/'package';package.mkdir();members={archive,root/'builds.jsonl'}
    members.update(notices)
    members.update(x for x in (root/'builds').rglob('*') if x.is_file())
    index=[]
    with tarfile.open(package/'payload.tar','w',format=tarfile.PAX_FORMAT) as tf:
        for path in sorted(members):
            data=path.read_bytes();name=path.relative_to(root).as_posix();info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o644
            tf.addfile(info,io.BytesIO(data));index.append({'member':name,'sha256':hashlib.sha256(data).hexdigest(),'size':len(data)})
    (package/'artifact-index.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in index))
    shutil.copyfile(root/'builds.jsonl',package/'builds.jsonl')
    shutil.copyfile(Path(__file__),package/'collect_go_obfuscated.py')
    for notice in notices: shutil.copyfile(notice,package/notice.name)
    import pyarrow as pa
    import pyarrow.parquet as pq
    pq.write_table(pa.Table.from_pylist([{'build_id':r['build_id'],'baseline_build_id':r.get('baseline_build_id'),
                                        'language':'go','os':r['target']['os'],'arch':r['target']['arch'],
                                        'track':r['track'],'status':r['status'],'qualified':False,
                                        'manifest_json':json.dumps(r,sort_keys=True)} for r in rows]),package/'builds.parquet',compression='zstd')
    checks=[{'path':x.name,'sha256':sha(x),'size':x.stat().st_size} for x in sorted(package.iterdir()) if x.is_file()]
    (package/'checksums.json').write_text(json.dumps(checks,indent=2)+'\n')
    print(json.dumps({'attempts':len(rows),'successes':sum(r['status']=='success' for r in rows),'payload_members':len(index)}),flush=True)
    if args.publish:
        from huggingface_hub import HfApi,hf_hub_download
        repo_id='sjkim1127/decbench-multilang-corpus';api=HfApi()
        print(api.upload_folder(repo_id=repo_id,repo_type='dataset',folder_path=package,path_in_repo='obfuscated/go-garble-2026-10-23',commit_message='Add source-backed Go clean/garble pairs for ELF PE and Mach-O'),flush=True)
        card=Path(hf_hub_download(repo_id,'README.md',repo_type='dataset')).read_text()
        if 'config_name: obfuscation_builds' not in card:
            card=card.replace('---\n# DecBench','- config_name: obfuscation_builds\n  data_files:\n  - split: raw\n    path: obfuscated/*/*.parquet\n---\n# DecBench',1)
        card+='\n## Source-backed obfuscation pilot\n\nGo tomlv from BurntSushi/toml is paired with garble v0.15.0 outputs for Linux x86-64, Windows x86-64 and macOS ARM64. Original source, exact seed, generated transformed sources and compiler logs are retained. See `obfuscated/go-garble-2026-10-23/builds.jsonl` for actual build status. No semantic execution, replay-reproducibility or source/function mapping qualification is claimed.\n'
        print(api.upload_file(repo_id=repo_id,repo_type='dataset',path_in_repo='README.md',path_or_fileobj=card.encode(),commit_message='Expose source-backed obfuscation metadata'),flush=True)


if __name__=='__main__':main()
