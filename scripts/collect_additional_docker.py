"""Collect three newly supported languages from reviewed real upstream products."""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import shutil
from upstream_sources import acquire,sha

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--image',default='decbench-additional-languages:20261023')
    p.add_argument('--languages',nargs='+',choices=['fortran','d','nim'],default=['fortran','d','nim']);args=p.parse_args()
    root=args.output.resolve();root.mkdir(parents=True,exist_ok=False)
    image=json.loads(subprocess.run(['docker','image','inspect',args.image],capture_output=True,text=True,check=True).stdout)[0]
    (root/'image.json').write_text(json.dumps(image,indent=2)+'\n')
    (root/'tooling').mkdir()
    for name in ('container_additional.py','collect_additional_docker.py','upstream_sources.py'):shutil.copyfile(ROOT/'scripts'/name,root/'tooling'/name)
    config=json.loads((ROOT/'configs/additional-language-projects.json').read_text());projects=config['projects'];jobs=[];dependencies={}
    if 'nim' in args.languages:
        for dependency in config.get('dependencies',[]):
            source,provenance=acquire(dependency,root/'dependencies/nim');dependencies['nim']={'source':source,'provenance':provenance}
    for project in projects:
        if project['language'] not in args.languages:continue
        folder=root/project['language'];source,provenance=acquire(project,folder)
        for opt in ('0','2'):
            for attempt in (1,2):jobs.append((project,folder,source,provenance,opt,attempt))
    def build(item):
        project,folder,source,provenance,opt,attempt=item;out=folder/('opt'+opt)/str(attempt);out.mkdir(parents=True)
        recipe=out/'recipe.json';recipe.write_text(json.dumps({'project':project,'opt':opt},indent=2))
        argv=['docker','run','--rm','--platform','linux/arm64','--network','none','--read-only','--cap-drop=ALL',
              '--security-opt=no-new-privileges','--memory=4g','--cpus=2','--pids-limit=512',
              '--user',f'{os.getuid()}:{os.getgid()}','--tmpfs','/tmp:rw,nosuid,nodev,size=1g',
              '-v',f'{source}:/src:ro','-v',f'{out}:/out:rw','-v',f'{recipe}:/recipe.json:ro',
              '-v',f'{folder / "source-provenance.json"}:/provenance.json:ro',
              '-v',f'{ROOT / "scripts/container_additional.py"}:/collector.py:ro',
              '-v',f'{ROOT / "scripts/upstream_sources.py"}:/upstream_sources.py:ro',
              *(['-v',f'{dependencies["nim"]["source"]}:/deps/nim:ro'] if project['language']=='nim' else []),
              image['Id'],'python3','/collector.py']
        result=subprocess.run(argv,capture_output=True,text=True,timeout=3600)
        (out/'docker.stdout').write_text(result.stdout);(out/'docker.stderr').write_text(result.stderr)
        if not (out/'report.json').exists():raise RuntimeError('Infrastructure failure: '+result.stderr[-1500:])
        report=json.loads((out/'report.json').read_text())
        artifacts=[f for f in out.iterdir() if f.is_file()]
        # Compiler-generated C/intermediate build metadata is derived evidence, not authored corpus source.
        for subfolder in ('nimcache','cmake-build'):
            if (out/subfolder).exists():
                import tarfile
                archive=out/(subfolder+'.tar')
                with tarfile.open(archive,'w') as tf:tf.add(out/subfolder,arcname=subfolder)
                artifacts.append(archive)
        record={'schema_version':'opensource-0.1.0','language':project['language'],'project':project['repository'],
                'source':provenance,'target':{'os':'linux','format':'elf','arch':'aarch64','abi':'aarch64-linux-gnu'},
                'profile':'opt'+opt,'attempt':attempt,'status':report['status'],'report':report,
                'image_identity':image['Id'],'docker_argv':argv,'qualified':False,'eval_ready':{},
                'source_origin':'upstream-open-source','collector_supplied_harness':False,'dataset_authored_program_source':False,
                'dependencies':[dependencies['nim']['provenance']] if project['language']=='nim' else [],
                'artifacts':[{'path':f.relative_to(root).as_posix(),'sha256':sha(f),'size':f.stat().st_size} for f in sorted(artifacts)]}
        (out/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
        print(project['language']+' '+record['profile']+' attempt '+str(attempt)+': '+record['status'],flush=True)
        return record
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:records=list(pool.map(build,jobs))
    (root/'attempts.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
    return int(any(r['status']!='success' for r in records))


if __name__=='__main__':raise SystemExit(main())
