"""Collect upstream bc7enc whole-project CMake builds and replay evidence."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import argparse

ROOT=Path(__file__).resolve().parents[1]

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def checked(args):return subprocess.check_output([str(x) for x in args])

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);args=p.parse_args()
    out=args.output.resolve()
    if out.exists():raise ValueError('Use fresh output directory')
    out.mkdir(parents=True)
    project=next(x for x in json.loads((ROOT/'configs/native-projects-batch2.json').read_text())['projects'] if x['id']=='richgel999-bc7enc_rdo')
    checkout=ROOT/'corpus/native-batch2-local-macos-aarch64/sources'/project['id']
    git=lambda *args: checked(['git','-C',checkout,*args])
    commit=git('rev-parse','HEAD').decode().strip()
    if commit!=project['commit_sha'] or git('status','--porcelain').strip():raise ValueError('Source checkout changed')
    if hashlib.sha256(git('show',commit+':'+project['license_file'])).hexdigest()!=project['license_sha256']:
        raise ValueError('License blob changed')
    (out/'sources').mkdir();snapshot=out/'sources'/f'{project["id"]}.tar'
    checked(['git','-C',checkout,'archive','--format=tar','--output='+str(snapshot),commit])
    extracted=out/'upstream';extracted.mkdir()
    with tarfile.open(snapshot) as tf:tf.extractall(extracted,filter='data')
    image=json.loads(checked(['docker','image','inspect','decbench-additional-languages:20261023']))[0]
    (out/'image.json').write_text(json.dumps(image,indent=2)+'\n')
    source={**project,'tree_hash':git('rev-parse','HEAD^{tree}').decode().strip(),
            'snapshot_path':snapshot.relative_to(out).as_posix(),'snapshot_sha256':sha(snapshot)}
    def build(job):
        profile,attempt=job;folder=out/'builds'/project['id']/profile/str(attempt)
        folder.mkdir(parents=True)
        argv=['docker','run','--rm','--network','none','--read-only','--cap-drop=ALL',
              '--security-opt=no-new-privileges','--memory=4g','--cpus=2','--pids-limit=512',
              '--user',f'{os.getuid()}:{os.getgid()}','--tmpfs','/tmp:rw,nosuid,nodev,size=1g',
              '-e','CORPUS_PROFILE='+profile,'-v',f'{extracted}:/src:ro','-v',f'{folder}:/out:rw',
              '-v',f'{ROOT/"scripts/container_cpp_whole.py"}:/collector.py:ro',image['Id'],
              '/usr/bin/python3','/collector.py']
        result=subprocess.run(argv,capture_output=True,timeout=3600)
        (folder/'docker.stdout').write_bytes(result.stdout);(folder/'docker.stderr').write_bytes(result.stderr)
        report_path=folder/'report.json'
        report=json.loads(report_path.read_text()) if report_path.exists() else {'status':'failed','error':'container failed before report','commands':[],'tools':{}}
        tools=report.get('tools',{});driver=tools.get('g++',{})
        record={'schema_version':'native-0.3.0','project':project['id'],'language':'cpp','source':source,
            'target':{'os':'linux','arch':'aarch64','format':'elf','abi':'aarch64-linux-gnu'},
            'profile':profile,'attempt':attempt,'host':{'runner_image':'docker','runner_image_version':image['Id']},
            'toolchain':{'family':'gcc','driver':driver.get('path'),'sha256':driver.get('sha256'),
                         'version':driver,'image_id':image['Id']},
            'environment':report.get('environment',{}),'commands':report.get('commands',[]),
            'status':report['status'],'error':report.get('error'),'qualified':False,'eval_ready':{},
            'split_group':project['repository_url'],'collector_sha256':sha(ROOT/'scripts/container_cpp_whole.py'),
            'build_scope':'whole-project-multi-translation-unit','docker_argv':argv,
            'debug_relation':report.get('debug_relation'),'execution_tests':'not-run',
            'child_argv_trace':'ninja-verbose-only'}
        # Preserve CMake metadata and all produced objects without requiring standalone files.
        build_dir=folder/'cmake-build'
        if build_dir.exists():
            with tarfile.open(folder/'cmake-build.tar.gz','w:gz') as tf:tf.add(build_dir,arcname='cmake-build')
        record['artifacts']=[{'path':f.relative_to(out).as_posix(),'sha256':sha(f),'size':f.stat().st_size}
                             for f in sorted(folder.iterdir()) if f.is_file()]
        (folder/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
        print(profile,attempt,record['status'],record.get('error'),flush=True);return record
    with ThreadPoolExecutor(max_workers=2) as pool: rows=list(pool.map(build,[(p,n) for p in ('O2','O2-LTO') for n in (1,2)]))
    (out/'attempts.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    for profile in ('O2','O2-LTO'):
        pair=[r for r in rows if r['profile']==profile]
        hashes=[[a['sha256'] for a in r['artifacts'] if a['path'].endswith('/binary.unstripped')] for r in pair]
        replay={'project':project['id'],'profile':profile,'attempts':2,'statuses':[r['status'] for r in pair],
                'artifact_hash_equal':{'binary.unstripped':len(hashes)==2 and all(hashes) and hashes[0]==hashes[1]}}
        (out/'builds'/project['id']/profile/'replay.json').write_text(json.dumps(replay,indent=2)+'\n')
    print(json.dumps({'attempts':len(rows),'successes':sum(r['status']=='success' for r in rows)}),flush=True)

if __name__=='__main__':main()
