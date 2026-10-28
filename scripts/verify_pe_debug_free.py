"""Independently inspect derived PE debug directories and exported symbols."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

import pyarrow.parquet as pq

ROOT=Path(__file__).resolve().parents[1]

def digest(data):return hashlib.sha256(data).hexdigest()

def inspect(tool,path):
    p=subprocess.run([str(tool),'--coff-debug-directory','--coff-exports',str(path)],capture_output=True,text=True,timeout=60)
    if p.returncode:raise ValueError('llvm-readobj failed: '+p.stderr[-500:])
    out=p.stdout
    if 'DebugDirectory [\n]' not in out:raise ValueError('Debug directory was not removed')
    return '\n'.join(line for line in out.splitlines() if not line.startswith('File: '))

def exports(tool,path):
    p=subprocess.run([str(tool),'--coff-exports',str(path)],capture_output=True,text=True,timeout=60)
    if p.returncode:raise ValueError('llvm-readobj exports failed: '+p.stderr[-500:])
    return '\n'.join(line for line in p.stdout.splitlines() if not line.startswith('File: '))

def main():
    p=argparse.ArgumentParser();p.add_argument('--package',required=True,type=Path);p.add_argument('--output',required=True,type=Path);args=p.parse_args()
    package=args.package.resolve();out=args.output.resolve()
    if out.exists():raise ValueError('Output already exists')
    out.mkdir(parents=True);tool=Path('/opt/homebrew/opt/llvm/bin/llvm-readobj').resolve()
    version=subprocess.check_output([str(tool),'--version'],text=True)
    rows=pq.read_table(package/'data/attempts.parquet').to_pylist();by_shard={}
    for row in rows:
        if row['status']=='success':by_shard.setdefault(row['payload_shard'],[]).append(row)
    checks=[]
    with tempfile.TemporaryDirectory(prefix='pe-independent-') as temp:
        target=Path(temp)/'candidate.dll'
        for shard,items in sorted(by_shard.items()):
            wanted={json.loads(r['manifest_json'])['artifacts'][0]['path']:r for r in items}
            with tarfile.open(package/shard,'r:gz') as tf:
                for member in tf:
                    if member.name not in wanted:continue
                    row=wanted.pop(member.name);manifest=json.loads(row['manifest_json']);binary=tf.extractfile(member).read()
                    if digest(binary)!=manifest['artifacts'][0]['sha256']:raise ValueError('Derived binary SHA mismatch')
                    target.write_bytes(binary);inspect(tool,target)
                    family=manifest['toolchain']['family'];arch=row['arch']
                    old=ROOT/'work/windows-matrix-40620095669'/f'windows-{family}-{arch}-40620095669'/f'native-windows-{family}-{arch}'/'builds'/row['project']/row['profile']/str(row['attempt'])/'binary.dll'
                    if digest(old.read_bytes())!=manifest['derivation']['original_binary_sha256']:raise ValueError('Original binary SHA mismatch')
                    if exports(tool,old)!=exports(tool,target):raise ValueError('PE exports changed: '+member.name)
                    checks.append({'build_id':row['build_id'],'binary_sha256':digest(binary),'original_sha256':digest(old.read_bytes()),
                                   'independent_debug_directory_empty':True,'exports_equal':True})
            if wanted:raise ValueError('Missing payload members: '+str(list(wanted)[:3]))
    summary={'records':len(rows),'checked':len(checks),'debug_directory_empty':len(checks),'export_tables_equal':len(checks),
             'failures':len(rows)-len(checks),'tool':str(tool),'tool_sha256':digest(tool.read_bytes()),'tool_version':version,
             'execution':'static-only','limitations':['no runtime semantics verified','other debug formats are not universally excluded']}
    (out/'records.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in checks));(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)

if __name__=='__main__':main()
