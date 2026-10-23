"""Open-source admission and byte provenance for corpus projects (no fixtures)."""
import hashlib
import json
from pathlib import Path
import subprocess

PROGRAM_SUFFIXES={'.c','.cc','.cpp','.h','.hpp','.swift','.zig','.d','.nim','.f','.f90','.f95','.f03','.f08'}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def checked(argv,cwd=None):
    p=subprocess.run([str(x) for x in argv],cwd=cwd,capture_output=True,timeout=1800)
    if p.returncode:raise RuntimeError(p.stderr.decode('utf8','replace')[-3000:])
    return p.stdout


def admit(project):
    if project.get('source_origin')!='upstream-open-source':raise ValueError('Only upstream open-source project code is admitted')
    if project.get('dataset_authored_program_source') is not False:raise ValueError('Dataset-authored programs are excluded')
    if project.get('collector_supplied_harness') is not False:raise ValueError('Collector-created harnesses are excluded')
    if not project.get('repository_url','').startswith('https://github.com/'):raise ValueError('Reviewed upstream repository required')
    if len(project.get('commit_sha',''))!=40:raise ValueError('Full immutable Git commit required')
    if not project.get('license_sha256'):raise ValueError('Reviewed license hash required')


def acquire(project,folder):
    admit(project);folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);source=folder/'source'
    if not source.exists():checked(['git','clone','--no-checkout',project['repository_url'],source])
    checked(['git','-C',source,'-c','core.autocrlf=false','-c','core.eol=lf','checkout','--detach',project['commit_sha']])
    commit=checked(['git','-C',source,'rev-parse','HEAD']).decode().strip()
    if commit!=project['commit_sha']:raise ValueError('Upstream commit mismatch')
    if checked(['git','-C',source,'status','--porcelain']).strip():raise ValueError('Upstream checkout contains local modifications')
    blob=checked(['git','-C',source,'show',commit+':'+project['license_file']])
    if hashlib.sha256(blob).hexdigest()!=project['license_sha256']:raise ValueError('Upstream license changed')
    if not (source/project['upstream_entrypoint']).is_file():raise ValueError('The selected entrypoint is not an upstream file')
    inventory={}
    for raw in checked(['git','-C',source,'ls-files','-z']).split(b'\0'):
        if not raw:continue
        path=raw.decode();file=source/path
        if file.is_file():inventory[path]=sha(file)
    snapshot=folder/'source.tar';checked(['git','-C',source,'archive','--format=tar','--output='+str(snapshot),'HEAD'])
    provenance={**project,'tree_hash':checked(['git','-C',source,'rev-parse','HEAD^{tree}']).decode().strip(),
                'source_snapshot_sha256':sha(snapshot),'tracked_files':inventory,
                'synthetic_fixture':False,'generated_harness':False}
    (folder/'source-provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    return source,provenance


def verify_program_sources(source,provenance):
    changed=[p for p,digest in provenance['tracked_files'].items()
             if Path(p).suffix.lower() in PROGRAM_SUFFIXES and (not (Path(source)/p).is_file() or sha(Path(source)/p)!=digest)]
    if changed:raise ValueError('Upstream program source was modified: '+', '.join(changed[:10]))
    return {'original_program_sources_unchanged':True,'dataset_authored_program_source':False,
            'collector_supplied_harness':False,'program_source_modifications':[]}
