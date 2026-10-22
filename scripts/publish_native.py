"""Package native raw attempts into separate HF metadata/payload shards."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_key(row):
    # Collector hash fixes recipe semantics; normalize only source/output workspace
    # paths in argv, retaining flag ordering, target and exact toolchain identities.
    commands = []
    for command in row['commands'][:2]:
        cwd = command['cwd']
        argv = []
        for arg in command['argv']:
            arg = arg.replace(cwd, 'SOURCE')
            arg = re.sub(r'[^\s]*?[/\\]builds[/\\]' + re.escape(row['project']) +
                         r'[/\\]' + re.escape(row['profile']) + r'[/\\][12](?=[/\\])', 'BUILD', arg)
            argv.append(arg)
        commands.append(argv)
    identity = {'source':row['source'], 'target':row['target'], 'profile':row['profile'],
                'toolchain':row['toolchain'], 'commands':commands,
                'collector_sha256':row['collector_sha256'],
                'runner_image':row['host'].get('runner_image'),
                'runner_image_version':row['host'].get('runner_image_version'),
                'sdk':row['host'].get('sdk_version'),'xcode':row['host'].get('xcode')}
    # Source snapshot path is packaging, not an input setting.
    identity['source'] = {k:v for k,v in row['source'].items() if k!='snapshot_path'}
    return hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--corpus', action='append', type=Path, required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--campaign',default='platforms-2026-10-23')
    parser.add_argument('--publish',action='store_true')
    parser.add_argument('--repo',default='sjkim1127/decbench-multilang-corpus')
    args=parser.parse_args()
    import pyarrow as pa
    import pyarrow.parquet as pq
    destination=args.output.resolve();destination.mkdir(parents=True,exist_ok=True)
    metadata=[];index=[];totals={}
    for corpus in args.corpus:
        corpus=corpus.resolve()
        rows=[json.loads(line) for line in (corpus/'attempts.jsonl').read_text().splitlines()]
        first=rows[0]; target=first['target']; cell=target['os']+'-'+target['arch']
        if cell in totals: raise ValueError('Duplicate campaign target cell; merge explicitly instead')
        totals[cell]={'attempts':len(rows),'successes':sum(r['status']=='success' for r in rows)}
        shard=destination/'payloads'/(cell+'.tar');shard.parent.mkdir(exist_ok=True)
        members={corpus/'attempts.jsonl'}
        for row in rows:
            if row['target']!=target: raise ValueError('Mixed target cells in one corpus')
            snapshot=corpus/row['source']['snapshot_path']
            if sha(snapshot)!=row['source']['snapshot_sha256']: raise ValueError('Snapshot changed')
            members.add(snapshot)
            folder=corpus/'builds'/row['project']/row['profile']/str(row['attempt'])
            members.add(folder/'manifest.json')
            members.add(folder.parent/'replay.json')
            for item in row.get('artifacts',[]):
                file=corpus/item['path']
                if sha(file)!=item['sha256'] or file.stat().st_size!=item['size']: raise ValueError('Artifact changed: '+str(file))
                members.add(file)
            replay=json.loads((folder.parent/'replay.json').read_text())
            metadata.append({'schema_version':row['schema_version'],'build_id':build_key(row),
                             'project':row['project'],'language':row['language'],'os':target['os'],
                             'format':target['format'],'arch':target['arch'],'abi':target['abi'],
                             'profile':row['profile'],'attempt':row['attempt'],'status':row['status'],
                             'qualified':False,'split_group':row['split_group'],
                             'payload_shard':shard.relative_to(destination).as_posix(),
                             'manifest_member':(folder/'manifest.json').relative_to(corpus).as_posix(),
                             'manifest_json':json.dumps(row,sort_keys=True),
                             'replay_json':json.dumps(replay,sort_keys=True)})
        with tarfile.open(shard,'w',format=tarfile.PAX_FORMAT) as tf:
            for member in sorted(members):
                data=member.read_bytes();name=member.relative_to(corpus).as_posix()
                info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o644
                tf.addfile(info,io.BytesIO(data))
                index.append({'shard':shard.relative_to(destination).as_posix(),'member':name,
                              'sha256':hashlib.sha256(data).hexdigest(),'size':len(data)})
    data=destination/'data';data.mkdir(exist_ok=True)
    pq.write_table(pa.Table.from_pylist(metadata),data/'attempts.parquet',compression='zstd')
    (destination/'artifact-index.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in index))
    summary={'campaign':args.campaign,'targets':totals,'distinct_build_ids':len({r['build_id'] for r in metadata}),
             'qualified':0,'source_projects':sorted({r['project'] for r in metadata})}
    (destination/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    root=Path(__file__).resolve().parents[1]
    collection=destination/'collection';collection.mkdir(exist_ok=True)
    for relative in ('configs/native-projects.json','configs/coverage-policy.json','configs/obfuscation-policy.json',
                     'configs/research/github-candidates.json','scripts/collect_native.py','scripts/publish_native.py',
                     'docs/PLATFORM_CAMPAIGN.md'):
        p=collection/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((root/relative).read_bytes())
    checks=[{'path':p.relative_to(destination).as_posix(),'sha256':sha(p),'size':p.stat().st_size}
            for p in sorted(destination.rglob('*')) if p.is_file() and p.name!='checksums.json']
    (destination/'checksums.json').write_text(json.dumps(checks,indent=2)+'\n')
    print(json.dumps(summary),flush=True)
    if args.publish:
        from huggingface_hub import HfApi, hf_hub_download
        api=HfApi();prefix='native/'+args.campaign
        result=api.upload_folder(repo_id=args.repo,repo_type='dataset',folder_path=destination,path_in_repo=prefix,
                                 commit_message='Add cross-platform raw native corpus campaign '+args.campaign)
        card=Path(hf_hub_download(args.repo,'README.md',repo_type='dataset')).read_text()
        config='- config_name: native_attempts\n  data_files:\n  - split: raw\n    path: native/*/data/*.parquet\n'
        if 'config_name: native_attempts' not in card:
            card=card.replace('---\n# DecBench',config+'---\n# DecBench',1)
        marker='## Native cross-platform campaigns'
        if marker in card: card=card[:card.index(marker)]
        card+='\n'+marker+'\n\nThe initial C/C++ Linux pilot above is supplemented by native raw attempts.\n'+\
              'Use config `native_attempts`; replay attempts are separate rows, not extra distinct builds.\n'+\
              'See `native/'+args.campaign+'/summary.json` for actual collected OS/format/architecture counts.\n'+\
              'Source snapshots retain per-file upstream licenses (MIT, BSD, zlib and other original notices).\n'+\
              'Source discovery candidates and obfuscation policy are not built obfuscated artifacts.\n'+\
              'All native records remain unqualified; PE/PDB links are raw evidence and dSYM UUIDs are checked.\n'
        commit=api.upload_file(repo_id=args.repo,repo_type='dataset',path_in_repo='README.md',
                               path_or_fileobj=card.encode(),commit_message='Expose native raw attempts and campaign limitations')
        print(commit,flush=True)


if __name__=='__main__': main()
