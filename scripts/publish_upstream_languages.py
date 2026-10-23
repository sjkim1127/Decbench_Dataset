"""Publish only verified upstream program products, with per-language indexes."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
from upstream_sources import admit,sha
from collect_native import observed_binary

ROOT=Path(__file__).resolve().parents[1]
PREFIX='opensource/languages-batch1-2026-10-23'


def primary_integrity(row):
    admit(row['source'])
    if row.get('dataset_authored_program_source') is not False or row.get('collector_supplied_harness') is not False:
        raise ValueError('Authored corpus programs/harnesses are prohibited')
    if row['status']!='success':raise ValueError('Only successful original upstream products enter the primary index')
    evidence=row.get('source_integrity') or row.get('report',{}).get('source_integrity',{})
    if evidence.get('original_program_sources_unchanged') is not True or evidence.get('program_source_modifications')!=[]:
        raise ValueError('Original upstream source integrity evidence is required')
    if row['qualified'] is not False:raise ValueError('This is raw acquisition, not qualification')


def identity(row,corpus,out):
    commands=row.get('commands') or row['report']['commands']
    normalized=[]
    for command in commands:
        if command['returncode']!=0:continue
        normalized.append([str(arg).replace(str(out),'BUILD').replace(str(corpus/'prepare'),'DEPS').replace(str(corpus/'source'),'SOURCE') for arg in command['argv']])
    # /out and /src are already stable paths for containerized compilers.
    payload={'source_snapshot_sha256':row['source']['source_snapshot_sha256'],'commit_sha':row['source']['commit_sha'],
             'project':row['project'],'language':row['language'],'profile':row['profile'],'target':row['target'],
             'image':row.get('image_identity'),'tools':row.get('tools') or row.get('report',{}).get('tools'),
             'dependencies':row.get('dependencies',[]),'dependency_pins_sha256':row.get('dependency_pins_sha256'),
             'commands':normalized}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--corpus',action='append',type=Path,required=True)
    parser.add_argument('--history',action='append',type=Path,default=[]);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--publish',action='store_true');args=parser.parse_args()
    destination=args.output.resolve();destination.mkdir(parents=True,exist_ok=True)
    reviewed_projects={p['repository']:p for p in json.loads((ROOT/'configs/additional-language-projects.json').read_text())['projects']}
    groups={};failed=[];history_roots=[]
    for corpus in args.corpus:
        corpus=corpus.resolve()
        rows=[json.loads(x) for x in (corpus/'attempts.jsonl').read_text().splitlines()]
        for row in rows:
            if row['status']!='success':failed.append({'corpus':corpus.name,'record':row});continue
            primary_integrity(row);groups.setdefault(row['language'],[]).append((corpus,row))
        history_roots.append(corpus)
    for corpus in args.history:
        corpus=corpus.resolve();history_roots.append(corpus)
        for line in (corpus/'attempts.jsonl').read_text().splitlines():
            row=json.loads(line)
            if row['status']!='success':failed.append({'corpus':corpus.name,'record':row})
    indexes=[];summaries={};all_rows=[];replays=[];derivation_failures=0
    for language,items in sorted(groups.items()):
        members={};metadata=[];binaries=[];source_entries={}
        for corpus,row in items:
            reviewed=reviewed_projects[row['project']]
            if (reviewed['commit_sha'],reviewed['license_sha256'])!=(row['source']['commit_sha'],row['source']['license_sha256']):
                raise ValueError('Source/permission evidence no longer matches the reviewed upstream project')
            artifact=next(a for a in row['artifacts'] if Path(a['path']).name=='binary.unstripped')
            binary=corpus/artifact['path'];out=binary.parent;observed=observed_binary(binary)
            if any(observed[k]!=row['target'][k] for k in ('format','arch')):raise ValueError('Observed binary target mismatch')
            # Docker compilers store source archives under <language>/; native collectors at the corpus root.
            folder=corpus/language if (corpus/language/'source.tar').exists() else corpus
            snapshot=folder/'source.tar'
            if sha(snapshot)!=row['source']['source_snapshot_sha256']:raise ValueError('Source archive identity mismatch')
            for file in (snapshot,folder/'source-provenance.json',out/'manifest.json'):
                members[file]=(corpus.name+'/'+file.relative_to(corpus).as_posix())
            source_entries[row['project']]={'repository_url':row['source']['repository_url'],'commit_sha':row['source']['commit_sha'],
                                           'tree_hash':row['source']['tree_hash'],'source_snapshot_sha256':sha(snapshot),
                                           'source_member':members[snapshot],'license_file':row['source']['license_file'],
                                           'license_sha256':row['source']['license_sha256'],'source_origin':'upstream-open-source'}
            source_entries[row['project']]['reviewed_license_spdx']=reviewed['license_spdx']
            for artifact in row['artifacts']:
                file=corpus/artifact['path']
                if sha(file)!=artifact['sha256'] or file.stat().st_size!=artifact['size']:raise ValueError('Artifact changed: '+str(file))
                members[file]=corpus.name+'/'+file.relative_to(corpus).as_posix()
            for relative in ('prepare/dependency-sources.tar','prepare/Package.resolved','prepare/dependency-commits.json',
                             'prepare/fetch.json','prepare/resolve.json','prepare/zig-env.json','dependencies/nim/source.tar',
                             'dependencies/nim/source-provenance.json','image.json'):
                file=corpus/relative
                if file.is_file():members[file]=corpus.name+'/'+relative
            for file in (corpus/'tooling').glob('*'):
                if file.is_file():members[file]=corpus.name+'/tooling/'+file.name
            uid=identity(row,corpus,out)
            binary_member=corpus.name+'/'+binary.relative_to(corpus).as_posix()
            metadata.append({'schema_version':'opensource-0.1.0','build_id':uid,'language':language,'project':row['project'],
                             'os':row['target']['os'],'format':row['target']['format'],'arch':row['target']['arch'],
                             'target_triple':row['target'].get('triple'),'profile':row['profile'],'attempt':row['attempt'],
                             'source_repository':row['source']['repository_url'],'source_commit':row['source']['commit_sha'],
                             'license_spdx':reviewed['license_spdx'],
                             'source_origin':'upstream-open-source','dataset_authored_program_source':False,'collector_supplied_harness':False,
                             'source_integrity_verified':True,'qualified':False,'status':'success',
                             'source_snapshot_sha256':row['source']['source_snapshot_sha256'],
                             'binary_sha256':sha(binary),'payload_shard':'payloads/'+language+'.tar','binary_member':binary_member,
                             'manifest_member':members[out/'manifest.json'],'manifest_json':json.dumps(row,sort_keys=True)})
            binaries.append({'build_id':uid,'profile':row['profile'],'target':row['target'],'attempt':row['attempt'],
                             'binary_sha256':sha(binary),'member':binary_member,'manifest_member':members[out/'manifest.json']})
        shard=destination/'payloads'/(language+'.tar');shard.parent.mkdir(exist_ok=True)
        with tarfile.open(shard,'w',format=tarfile.PAX_FORMAT) as tf:
            for file,member in sorted(members.items(),key=lambda item:item[1]):
                data=file.read_bytes();info=tarfile.TarInfo(member);info.size=len(data);info.mode=0o644;tf.addfile(info,io.BytesIO(data))
                kind='source_snapshot' if file.name=='source.tar' else 'primary_binary' if file.name=='binary.unstripped' else 'derived-or-metadata'
                indexes.append({'shard':'payloads/'+language+'.tar','member':member,'sha256':hashlib.sha256(data).hexdigest(),'size':len(data),'kind':kind})
        import pyarrow as pa
        import pyarrow.parquet as pq
        data=destination/'data'/language;data.mkdir(parents=True,exist_ok=True)
        pq.write_table(pa.Table.from_pylist(metadata),data/'attempts.parquet',compression='zstd')
        for uid in sorted({r['build_id'] for r in metadata}):
            pairs=[r for r in metadata if r['build_id']==uid]
            replays.append({'language':language,'build_id':uid,'attempts':len(pairs),'binary_hash_equal':len({r['binary_sha256'] for r in pairs})==1 if len(pairs)>1 else None})
        manifest={'config':language,'kind':'raw-upstream-products','language':language,'source_origin':'upstream-open-source',
                  'projects':source_entries,'binaries':binaries,'successful_attempts':len(metadata),'distinct_build_variants':len({r['build_id'] for r in metadata}),
                  'payload':PREFIX+'/payloads/'+language+'.tar','metadata':PREFIX+'/data/'+language+'/attempts.parquet',
                  'qualified':False,'function_count':None,'metrics':[]}
        manifest['files']=[{'path':PREFIX+'/'+file.relative_to(destination).as_posix(),'sha256':sha(file),'size':file.stat().st_size}
                           for file in (shard,data/'attempts.parquet')]
        manifest['artifact_index']=PREFIX+'/artifact-index.jsonl'
        config_dir=destination/'configs'/language;config_dir.mkdir(parents=True,exist_ok=True)
        (config_dir/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        summaries[language]={'projects':list(source_entries),'successful_attempts':len(metadata),'distinct_build_variants':manifest['distinct_build_variants'],
                             'targets':sorted({r['os']+'/'+r['arch'] for r in metadata})}
        all_rows.extend(metadata)
    history_dir=destination/'history';history_dir.mkdir(exist_ok=True)
    for corpus in history_roots:
        special=corpus/'postprocess-history'
        if special.exists():
            before=special/'attempts.before-recovery.jsonl'
            if before.exists():derivation_failures+=sum(json.loads(x)['status']=='failed' for x in before.read_text().splitlines())
            for file in special.rglob('*'):
                if file.is_file():
                    out=history_dir/corpus.name/file.relative_to(corpus);out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(file.read_bytes())
        for file in corpus.rglob('manifest.json'):
            if any(name in file.parts for name in ('scratch','global-cache','local-cache','source','dependencies','upstream','nimcache','cmake-build')):continue
            record=json.loads(file.read_text())
            if record.get('status')=='failed':
                out=history_dir/corpus.name/file.relative_to(corpus);out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(file.read_bytes())
                for log in file.parent.glob('command-*.*'):
                    (out.parent/log.name).write_bytes(log.read_bytes())
    (history_dir/'failed-records.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in failed))
    (destination/'artifact-index.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in indexes))
    (destination/'replays.json').write_text(json.dumps(replays,indent=2)+'\n')
    summary={'kind':'raw-upstream-only','languages':summaries,'successful_attempts':len(all_rows),
             'distinct_build_variants':sum(v['distinct_build_variants'] for v in summaries.values()),
             'primary_projects':len({r['project'] for r in all_rows}),'dataset_authored_programs':0,'collector_supplied_harnesses':0,
             'qualified':0,'prior_failed_collection_attempts':len(failed),'recovered_debug_derivation_failures':derivation_failures,'replay_pairs':replays}
    (destination/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    collection=destination/'collection';collection.mkdir(exist_ok=True)
    for relative in ('configs/additional-language-projects.json','scripts/upstream_sources.py','scripts/container_additional.py',
                     'scripts/collect_additional_docker.py','scripts/collect_additional_native.py','scripts/recover_zig_debug.py',
                     'scripts/publish_upstream_languages.py','docker/additional-languages.Dockerfile','docs/UPSTREAM_ONLY.md'):
        out=collection/relative;out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes((ROOT/relative).read_bytes())
    checks=[{'path':f.relative_to(destination).as_posix(),'sha256':sha(f),'size':f.stat().st_size}
            for f in sorted(destination.rglob('*')) if f.is_file() and f.name!='checksums.json']
    (destination/'checksums.json').write_text(json.dumps(checks,indent=2)+'\n')
    print(json.dumps(summary),flush=True)
    if args.publish:
        from huggingface_hub import HfApi,hf_hub_download
        repo='sjkim1127/decbench-multilang-corpus';api=HfApi()
        print(api.upload_folder(repo_id=repo,repo_type='dataset',folder_path=destination,path_in_repo=PREFIX,
                               commit_message='Add verified original Swift Zig Fortran D Nim upstream products'),flush=True)
        card=Path(hf_hub_download(repo,'README.md',repo_type='dataset')).read_text()
        if 'config_name: upstream_languages' not in card:
            card=card.replace('---\n# DecBench','- config_name: upstream_languages\n  data_files:\n  - split: raw\n    path: opensource/*/data/*/*.parquet\n---\n# DecBench',1)
        card+='\n## Verified original upstream language products\n\nThe `upstream_languages` config adds original Mint (Swift), ZLS (Zig), JSON-Fortran, DustMite (D), and Nimble (Nim) products. Every primary product has a reviewed GitHub repository, fixed full commit, original source archive and license hash, and byte checks that tracked program sources remained unchanged. Dataset-authored programs, collector-created entrypoint wrappers and harnesses are excluded. Compiler/upstream generated intermediate files are derived evidence only. See `'+PREFIX+'/summary.json` and per-language `configs/*/manifest.json` for actual collected counts and file indexes. Original-source archives, frozen dependencies, binaries and debug artifacts are preserved. All records remain raw/unqualified, without benchmark scores or validated function mappings. Earlier acquisition and debug-derivation failures remain history. The user-provided noelo-lab dataset was inspected as a packaging reference; its scores and corpus were not copied.\n'
        print(api.upload_file(repo_id=repo,repo_type='dataset',path_in_repo='README.md',path_or_fileobj=card.encode(),
                              commit_message='Expose upstream-only language configs and original-source admission policy'),flush=True)


if __name__=='__main__':main()
