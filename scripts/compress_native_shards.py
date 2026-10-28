"""Compress freshly packaged native tar shards without changing member bytes."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil

import pyarrow as pa
import pyarrow.parquet as pq


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda:stream.read(1024*1024),b''):h.update(data)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('package',type=Path);args=p.parse_args()
    root=args.package.resolve();changes={}
    for tar in sorted((root/'payloads').glob('*.tar')):
        output=tar.with_suffix('.tar.gz')
        if output.exists():raise ValueError('Compressed shard already exists')
        with tar.open('rb') as raw,output.open('wb') as destination:
            with gzip.GzipFile(fileobj=destination,mode='wb',filename='',mtime=0,compresslevel=3) as zipped:
                shutil.copyfileobj(raw,zipped,1024*1024)
        h=hashlib.sha256()
        with gzip.open(output,'rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
        if h.hexdigest()!=sha(tar):raise ValueError('Compressed tar verification failed')
        changes[tar.relative_to(root).as_posix()]=output.relative_to(root).as_posix()
    if not changes:raise ValueError('No uncompressed shards found')
    index=root/'artifact-index.jsonl'
    entries=[json.loads(line) for line in index.read_text().splitlines()]
    for entry in entries:entry['shard']=changes[entry['shard']]
    index.write_text(''.join(json.dumps(r)+'\n' for r in entries))
    path=root/'data/attempts.parquet';table=pq.read_table(path)
    index_column=table.schema.get_field_index('payload_shard')
    updated=[changes[value] for value in table['payload_shard'].to_pylist()]
    table=table.set_column(index_column,'payload_shard',pa.array(updated,type=pa.string()))
    pq.write_table(table,path,compression='zstd')
    # Original corpus files remain outside this fresh package; remove only the verified duplicate tar.
    for old in changes:(root/old).unlink()
    target=root/'collection/scripts/compress_native_shards.py';target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(Path(__file__),target)
    checks=[{'path':f.relative_to(root).as_posix(),'sha256':sha(f),'size':f.stat().st_size}
            for f in sorted(root.rglob('*')) if f.is_file() and f.name!='checksums.json']
    (root/'checksums.json').write_text(json.dumps(checks,indent=2)+'\n')
    print('Verified compressed shards',changes,flush=True)

if __name__=='__main__':main()
