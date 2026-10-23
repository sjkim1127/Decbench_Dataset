"""Acquire locked dependencies, then compile real CLI projects offline in Docker."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

ROOT=Path(__file__).resolve().parents[1]
IMAGE='rust@sha256:48b7f435b8fc6378ce43b44f15e3a47fd8919b2825f835c39bd4bd3da50af5b8'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(argv,timeout=3600):
    return subprocess.run([str(x) for x in argv],capture_output=True,text=True,timeout=timeout)


def check(argv):
    p=run(argv)
    if p.returncode:raise RuntimeError(p.stderr[-4000:])
    return p.stdout.strip()


def docker(source,dest,*,offline=True):
    return ['docker','run','--rm','--platform','linux/arm64','--read-only','--network','none' if offline else 'bridge',
            '--cap-drop=ALL','--security-opt=no-new-privileges','--pids-limit=512','--memory=4g','--cpus=2',
            '--user',f'{os.getuid()}:{os.getgid()}','--tmpfs','/tmp:rw,nosuid,nodev,size=1g',
            '-e','RUSTUP_TOOLCHAIN=1.99.1','-e','CARGO_HOME=/out/cargo-home',
            '-v',f'{source}:/src:ro','-v',f'{dest}:/out:rw','-w','/src']


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    root=args.output.resolve();root.mkdir(parents=True,exist_ok=False)
    registry=json.loads((ROOT/'configs/research/github-candidates.json').read_text())['projects']
    recipes=[]
    for repo,binary in [('BurntSushi/ripgrep','rg'),('sharkdp/hyperfine','hyperfine')]:
        locked=next(x for x in registry if x['repository']==repo)
        folder=root/repo.split('/')[1];folder.mkdir();source=folder/'source'
        check(['git','clone','--no-checkout',locked['url']+'.git',source])
        check(['git','-C',source,'checkout','--detach',locked['commit_sha']])
        if 'Permission is hereby granted' not in (source/'LICENSE-MIT').read_text():raise ValueError('Review upstream MIT license')
        check(['git','-C',source,'archive','--format=tar','--output='+str(folder/'source.tar'),'HEAD'])
        prepare=folder/'prepare';prepare.mkdir()
        argv=docker(source,prepare,offline=False)+[IMAGE,'cargo','vendor','--locked','--versioned-dirs','/out/vendor']
        result=run(argv);(prepare/'vendor.stderr').write_text(result.stderr);(prepare/'vendor.stdout').write_text(result.stdout)
        (prepare/'command.json').write_text(json.dumps({'argv':argv,'returncode':result.returncode},indent=2))
        if result.returncode:raise RuntimeError('Dependency acquisition failed: '+result.stderr[-2000:])
        config=prepare/'vendor-config.toml';config.write_text(result.stdout.replace('/out/vendor','/vendor'))
        with tarfile.open(prepare/'vendor.tar','w') as tf:tf.add(prepare/'vendor',arcname='vendor',recursive=True)
        for opt in ('0','2'):
            for attempt in (1,2):
                recipes.append((folder,source,prepare,config,{'repository_url':locked['url']+'.git','commit_sha':locked['commit_sha'],
                              'project':repo,'binary':binary,'opt':opt,'attempt':attempt}))
        print(repo+' dependencies frozen and vendored',flush=True)

    def build(item):
        folder,source,prepare,config,recipe=item;dest=folder/('opt'+recipe['opt'])/str(recipe['attempt']);dest.mkdir(parents=True)
        (dest/'recipe.json').write_text(json.dumps(recipe,indent=2))
        argv=docker(source,dest)+['-v',f'{prepare / "vendor"}:/vendor:ro','-v',f'{config}:/config/vendor.toml:ro',
                                 '-v',f'{dest / "recipe.json"}:/recipe.json:ro',
                                 '-v',f'{ROOT / "scripts/container_rust.py"}:/collector.py:ro',IMAGE,'python3','/collector.py']
        result=run(argv);(dest/'docker.stdout').write_text(result.stdout);(dest/'docker.stderr').write_text(result.stderr)
        if not (dest/'report.json').exists():raise RuntimeError('Container infrastructure failed: '+result.stderr[-1500:])
        report=json.loads((dest/'report.json').read_text())
        manifest={**recipe,'schema_version':'cargo-0.1.0','image_digest':IMAGE,'platform':'linux/arm64',
                  'source_snapshot_sha256':sha(folder/'source.tar'),'cargo_lock_sha256':sha(source/'Cargo.lock'),
                  'vendor_snapshot_sha256':sha(prepare/'vendor.tar'),'vendor_configuration':config.read_text(),
                  'source_license':{'spdx':'MIT OR Apache-2.0' if recipe['project']=='sharkdp/hyperfine' else 'MIT OR Unlicense',
                                    'evidence_sha256':sha(source/'LICENSE-MIT')},
                  'report':report,'qualified':False,'eval_ready':{},'docker_argv':argv,
                  'collector_sha256':sha(ROOT/'scripts/container_rust.py')}
        manifest['artifacts']=[{'path':f.relative_to(root).as_posix(),'sha256':sha(f),'size':f.stat().st_size}
                               for f in sorted(dest.iterdir()) if f.is_file()]
        (dest/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        print(recipe['project']+' opt'+recipe['opt']+' attempt '+str(recipe['attempt'])+': '+report['status'],flush=True)
        return manifest
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(build,recipes))
    (root/'attempts.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    return int(any(r['report']['status']!='success' for r in rows))


if __name__=='__main__':raise SystemExit(main())
