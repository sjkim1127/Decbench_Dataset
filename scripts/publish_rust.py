"""Package full Rust CLI builds with source, vendored dependencies and raw logs."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--corpus',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--history',type=Path,action='append',default=[])
    parser.add_argument('--publish',action='store_true');args=parser.parse_args()
    root=args.corpus.resolve();destination=args.output.resolve();destination.mkdir(parents=True,exist_ok=True)
    rows=[json.loads(x) for x in (root/'attempts.jsonl').read_text().splitlines()]
    from collect_native import observed_binary
    metadata=[];index=[];replays=[]
    for project in sorted({r['project'] for r in rows}):
        records=[r for r in rows if r['project']==project];name=project.split('/')[-1]
        folder=root/name
        assert sha(folder/'source.tar')==records[0]['source_snapshot_sha256']
        assert sha(folder/'prepare/vendor.tar')==records[0]['vendor_snapshot_sha256']
        members={folder/'source.tar',folder/'prepare/vendor.tar',folder/'prepare/vendor-config.toml',
                 folder/'prepare/vendor.stdout',folder/'prepare/vendor.stderr',folder/'prepare/command.json'}
        for row in records:
            identity={'source_snapshot_sha256':row['source_snapshot_sha256'], 'vendor_snapshot_sha256':row['vendor_snapshot_sha256'],
                      'commit_sha':row['commit_sha'],'image_digest':row['image_digest'],'project':project,'binary':row['binary'],
                      'opt':row['opt'],'environment':row['report']['environment'],
                      'actual_tools':row['report']['actual_toolchain_binaries'],'collector_sha256':row['collector_sha256']}
            build_id=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
            dest=folder/('opt'+row['opt'])/str(row['attempt']);members.add(dest/'manifest.json')
            for artifact in row['artifacts']:
                f=root/artifact['path']
                if sha(f)!=artifact['sha256'] or f.stat().st_size!=artifact['size']:raise ValueError('Artifact changed')
                members.add(f)
            if row['report']['status']=='success':
                observed=observed_binary(dest/'binary.unstripped')
                if observed!={'format':'elf','arch':'aarch64'}:raise ValueError('Unexpected Rust CLI target')
            metadata.append({'schema_version':'cargo-0.1.0','project':project,'language':'rust','os':'linux',
                             'format':'elf','arch':'aarch64','abi':'aarch64-linux-gnu','profile':'opt'+row['opt'],
                             'attempt':row['attempt'],'build_id':build_id,'status':row['report']['status'],
                             'qualified':False,'split_group':row['repository_url'],
                             'payload_shard':'payloads/'+name+'.tar','manifest_member':(dest/'manifest.json').relative_to(root).as_posix(),
                             'manifest_json':json.dumps(row,sort_keys=True)})
        for opt in sorted({r['opt'] for r in records}):
            a,b=[folder/('opt'+opt)/str(i) for i in (1,2)]
            replays.append({'project':project,'opt':opt,'artifact_hash_equal':{n:sha(a/n)==sha(b/n) if (a/n).exists() and (b/n).exists() else None
                                                                             for n in ('binary.unstripped','binary.debug','binary.stripped')}})
        target=destination/'payloads'/(name+'.tar');target.parent.mkdir(exist_ok=True)
        with tarfile.open(target,'w',format=tarfile.PAX_FORMAT) as tf:
            for path in sorted(members):
                data=path.read_bytes();member=path.relative_to(root).as_posix();info=tarfile.TarInfo(member);info.size=len(data);info.mode=0o644
                tf.addfile(info,io.BytesIO(data));index.append({'shard':target.relative_to(destination).as_posix(),'member':member,
                                                             'sha256':hashlib.sha256(data).hexdigest(),'size':len(data)})
    history=[]
    for source in args.history:
        source=source.resolve()
        reports=list(source.rglob('report.json'));history.append({'campaign':source.name,'build_reports':len(reports),
                                                               'classification':'collector-configuration-failure-before-source-compilation'})
        for pattern in ('**/report.json','**/cargo.stderr','**/vendor.stderr','**/command.json'):
            for original in source.glob(pattern):
                out=destination/'history'/source.name/original.relative_to(source)
                out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(original.read_bytes())
    import pyarrow as pa
    import pyarrow.parquet as pq
    data=destination/'data';data.mkdir(exist_ok=True)
    pq.write_table(pa.Table.from_pylist(metadata),data/'attempts.parquet',compression='zstd')
    (destination/'artifact-index.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in index))
    (destination/'replays.json').write_text(json.dumps(replays,indent=2)+'\n')
    (destination/'history.json').write_text(json.dumps(history,indent=2)+'\n')
    summary={'projects':sorted({r['project'] for r in metadata}),'attempts':len(metadata),
             'successful_attempts':sum(r['status']=='success' for r in metadata),'distinct_build_variants':len({r['build_id'] for r in metadata}),
             'qualified':0,'replays':replays,'prior_infrastructure_failures':history}
    (destination/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    source_root=Path(__file__).resolve().parents[1]
    for name in ('container_rust.py','collect_rust.py','publish_rust.py'):
        (destination/name).write_bytes((source_root/'scripts'/name).read_bytes())
    checks=[{'path':p.relative_to(destination).as_posix(),'sha256':sha(p),'size':p.stat().st_size}
            for p in sorted(destination.rglob('*')) if p.is_file() and p.name!='checksums.json']
    (destination/'checksums.json').write_text(json.dumps(checks,indent=2)+'\n')
    print(json.dumps(summary),flush=True)
    if args.publish:
        from huggingface_hub import HfApi,hf_hub_download
        repo='sjkim1127/decbench-multilang-corpus';api=HfApi()
        print(api.upload_folder(repo_id=repo,repo_type='dataset',folder_path=destination,path_in_repo='rust/cli-batch1-2026-10-23',
                                commit_message='Add raw ripgrep and hyperfine CLI builds with frozen vendored dependencies'),flush=True)
        card=Path(hf_hub_download(repo,'README.md',repo_type='dataset')).read_text()
        if 'config_name: rust_cli_attempts' not in card:
            card=card.replace('---\n# DecBench','- config_name: rust_cli_attempts\n  data_files:\n  - split: raw\n    path: rust/*/data/*.parquet\n---\n# DecBench',1)
        card+='\n## Rust full CLI collection\n\nRaw ripgrep and hyperfine Linux ARM64 CLI builds retain fixed source commits, Cargo.lock, vendored dependency source/licenses, exact Rust 1.99.1 Docker identity, full build logs and split debug artifacts. Compilation is offline; Cargo build scripts and procedural macro tools execute inside the limited container, while final corpus CLIs are never run. Opt0/opt2 each have two independent attempts. This is raw collection, without function mapping or semantic validation. Earlier collector configuration failures are retained in the campaign history. See `rust/cli-batch1-2026-10-23/summary.json`.\n'
        print(api.upload_file(repo_id=repo,repo_type='dataset',path_in_repo='README.md',path_or_fileobj=card.encode(),
                              commit_message='Expose raw Rust CLI collection metadata and acquisition limitations'),flush=True)


if __name__=='__main__':main()
