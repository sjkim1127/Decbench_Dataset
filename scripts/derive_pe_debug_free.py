"""Derive debug-directory-free PE inputs while preserving executable sections."""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import struct
import tarfile

import pyarrow as pa
import pyarrow.parquet as pq

ROOT=Path(__file__).resolve().parents[1]
SOURCE_REVISION='c330aafd6f2b0627b299d65728ea992a4082f8ab'
REPO='sjkim1127/decbench-multilang-corpus'

def sha(data):return hashlib.sha256(data).hexdigest()
def overlap(a,b):return a[0]<b[1] and b[0]<a[1]

def transform(raw):
    """Reject ambiguous layouts; only zero verified non-executable debug regions."""
    if raw[:2]!=b'MZ':raise ValueError('Missing MZ signature')
    pe=struct.unpack_from('<I',raw,0x3c)[0]
    if raw[pe:pe+4]!=b'PE\0\0':raise ValueError('Missing PE signature')
    machine,count=struct.unpack_from('<HH',raw,pe+4)
    symptr,symcount=struct.unpack_from('<II',raw,pe+12)
    if symptr or symcount:raise ValueError('COFF symbols exist; refusing incomplete stripping')
    optsize=struct.unpack_from('<H',raw,pe+20)[0];opt=pe+24
    magic=struct.unpack_from('<H',raw,opt)[0]
    if magic not in (0x10b,0x20b):raise ValueError('Unexpected PE optional header')
    diroff=opt+(96 if magic==0x10b else 112)
    dircount=struct.unpack_from('<I',raw,opt+(92 if magic==0x10b else 108))[0]
    if dircount<7 or diroff+min(dircount,16)*8>opt+optsize:raise ValueError('Invalid directory count')
    if struct.unpack_from('<II',raw,diroff+4*8)!=(0,0):raise ValueError('Signed PE requires separate policy')
    if struct.unpack_from('<I',raw,opt+64)[0]!=0:raise ValueError('Nonzero PE checksum requires recomputation')
    sections=[]
    for i in range(count):
        off=opt+optsize+i*40
        name=raw[off:off+8].rstrip(b'\0').decode('ascii','replace')
        vsize,va,rsize,rptr=struct.unpack_from('<IIII',raw,off+8)
        flags=struct.unpack_from('<I',raw,off+36)[0]
        if rptr+rsize>len(raw):raise ValueError('Truncated section')
        if name.startswith(('.debug','.zdebug')):raise ValueError('Unexpected embedded DWARF section')
        sections.append({'name':name,'va':va,'vsize':vsize,'raw':rptr,'raw_size':rsize,'flags':flags})
    def rva_range(rva,size):
        matches=[s for s in sections if s['va']<=rva and rva+size<=s['va']+s['raw_size']]
        if len(matches)!=1:raise ValueError('Unmapped or ambiguous RVA range')
        s=matches[0];begin=s['raw']+rva-s['va'];return (begin,begin+size),s
    debug_rva,debug_size=struct.unpack_from('<II',raw,diroff+6*8)
    if not debug_rva or not debug_size or debug_size%28:raise ValueError('Missing or malformed PE debug directory')
    directory,sec=rva_range(debug_rva,debug_size)
    if sec['flags']&0x20000000:raise ValueError('Debug directory overlaps executable section')
    other=[]
    for i in range(min(dircount,16)):
        if i in (4,6):continue
        rv,size=struct.unpack_from('<II',raw,diroff+i*8)
        if rv and size:
            try: span,_=rva_range(rv,size)
            except ValueError as exc: raise ValueError(f'Cannot verify data directory {i}') from exc
            other.append((i,span))
    ranges=[directory]; debug_types=[];codeview=[]
    for off in range(directory[0],directory[1],28):
        kind,size,addr,ptr=struct.unpack_from('<IIII',raw,off+12);debug_types.append(kind)
        if not size:continue
        if not ptr or ptr+size>len(raw):raise ValueError('Invalid debug payload')
        holders=[s for s in sections if s['raw']<=ptr and ptr+size<=s['raw']+s['raw_size']]
        if len(holders)!=1 or holders[0]['flags']&0x20000000:raise ValueError('Debug payload is not in a unique non-executable section')
        if addr:
            expected,_=rva_range(addr,size)
            if expected!=(ptr,ptr+size):raise ValueError('Debug payload RVA and file offset disagree')
        ranges.append((ptr,ptr+size))
        if kind==2 and raw[ptr:ptr+4]==b'RSDS':codeview.append((ptr,ptr+size))
    if len(codeview)!=1 or raw.count(b'RSDS')!=1:raise ValueError('Ambiguous CodeView signature')
    for target in ranges:
        for index,other_span in other:
            if overlap(target,other_span):raise ValueError(f'Debug bytes overlap data directory {index}')
    output=bytearray(raw)
    for a,b in ranges:output[a:b]=b'\0'*(b-a)
    output[diroff+6*8:diroff+7*8]=b'\0'*8
    result=bytes(output)
    if b'RSDS' in result:raise ValueError('Residual CodeView signature')
    preserved=[]
    for s in sections:
        if s['flags']&0x20000000:
            span=(s['raw'],s['raw']+s['raw_size'])
            if raw[span[0]:span[1]]!=result[span[0]:span[1]]:raise ValueError('Executable section changed')
            preserved.append({'name':s['name'],'sha256':sha(raw[span[0]:span[1]]),'size':s['raw_size']})
    if not preserved:raise ValueError('No executable sections')
    return result,{'method':'zero-validated-pe-debug-directory-and-payloads',
        'debug_directory_before':{'rva':debug_rva,'size':debug_size,'entry_types':debug_types},
        'debug_directory_after':{'rva':0,'size':0},'coff_symbol_table_before':{'offset':symptr,'count':symcount},
        'codeview_rsds_after':0,'debug_sections_after':0,'signed_pe':False,'checksum_before':0,
        'zeroed_file_ranges':[{'offset':a,'size':b-a} for a,b in ranges],
        'executable_sections_preserved':preserved,
        'limits':['does not remove required PE exports or unwind metadata','no semantic execution validation']}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--smoke',action='store_true')
    args=p.parse_args();out=args.output.resolve()
    if out.exists():raise ValueError('Use a fresh output directory')
    out.mkdir(parents=True);metadata=[];filemap=defaultdict(list);stats=Counter()
    datasets=[('msvc',ROOT/'shards/windows-msvc-20261028/data/attempts.parquet'),
              ('clang-cl',ROOT/'shards/windows-clang-cl-20261028/data/attempts.parquet')]
    for family,parquet in datasets:
        original=pq.read_table(parquet).to_pylist()
        if args.smoke:original=original[:1]
        for row in original:
            source=json.loads(row['manifest_json']);arch=row['arch'];attempt=row['attempt']
            path=ROOT/'work/windows-matrix-40620095669'/f'windows-{family}-{arch}-40620095669'/f'native-windows-{family}-{arch}'/'builds'/row['project']/row['profile']/str(attempt)/'binary.dll'
            raw=path.read_bytes();artifacts={Path(x['path']).name:x for x in source['artifacts']}
            if sha(raw)!=artifacts['binary.dll']['sha256']:raise ValueError('Original PE SHA mismatch')
            base='native/windows-'+family+'-2026-10-28'
            buildid=sha(('pe-debug-free-v1:'+row['build_id']).encode())
            folder=Path('builds')/family/arch/row['project']/row['profile']/str(attempt)
            member=(folder/'binary.dll').as_posix();manifest_member=(folder/'manifest.json').as_posix()
            derived={**source,'schema_version':'native-0.3.0','build_id':buildid,'status':'success',
                     'qualified':False,'eval_ready':{},'track':'pe-debug-directory-free',
                     'original_artifacts':source['artifacts'],
                     'derivation':{'source_dataset_repo':REPO,'source_dataset_revision':SOURCE_REVISION,
                         'original_payload_repo_path':base+'/'+row['payload_shard'],
                         'original_artifact_index_repo_path':base+'/artifact-index.jsonl',
                         'original_manifest_member':row['manifest_member'],'original_binary_sha256':sha(raw),
                         'pdb_sha256':artifacts['binary.pdb']['sha256'],'collector_sha256':sha(Path(__file__).read_bytes())},
                     'artifacts':[]}
            try:
                binary,proof=transform(raw);stats['success']+=1
                derived['derivation']['validation']=proof
                derived['artifacts']=[{'path':member,'sha256':sha(binary),'size':len(binary)}]
                filemap[arch].append((member,binary))
            except ValueError as exc:
                stats['failed']+=1;derived['status']='failed';derived['error']=str(exc)
            manifest_bytes=(json.dumps(derived,sort_keys=True,indent=2)+'\n').encode()
            filemap[arch].append((manifest_member,manifest_bytes))
            metadata.append({'schema_version':'native-0.3.0','build_id':buildid,'project':row['project'],
                'language':row['language'],'os':'windows','format':'pe','arch':arch,'abi':row['abi'],
                'profile':row['profile'],'attempt':attempt,'status':derived['status'],'qualified':False,
                'split_group':row['split_group'],'payload_shard':'payloads/windows-'+arch+'.tar.gz',
                'manifest_member':manifest_member,'manifest_json':json.dumps(derived,sort_keys=True),
                'replay_json':json.dumps({'original_build_id':row['build_id'],'derivation':'pe-debug-free-v1'})})
    indexes=[]
    for arch,entries in sorted(filemap.items()):
        shard='payloads/windows-'+arch+'.tar.gz';dest=out/shard;dest.parent.mkdir(parents=True,exist_ok=True)
        import io
        with dest.open('wb') as raw:
            with gzip.GzipFile(fileobj=raw,mode='wb',compresslevel=3,mtime=0,filename='') as zipped:
                with tarfile.open(fileobj=zipped,mode='w|',format=tarfile.PAX_FORMAT) as tf:
                    for member,data in sorted(entries):
                        info=tarfile.TarInfo(member);info.size=len(data);info.mode=0o644;tf.addfile(info,io.BytesIO(data))
                        indexes.append({'shard':shard,'member':member,'sha256':sha(data),'size':len(data)})
    (out/'data').mkdir();pq.write_table(pa.Table.from_pylist(metadata),out/'data/attempts.parquet',compression='zstd')
    (out/'artifact-index.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in indexes))
    (out/'derive_pe_debug_free.py').write_bytes(Path(__file__).read_bytes())
    summary={'source_repo':REPO,'source_revision':SOURCE_REVISION,'records':len(metadata),
             'successes':stats['success'],'failures':stats['failed'],'qualified':0,
             'description':'debug-directory-free PE; exported symbols and unwind information are preserved',
             'original_pdb_and_sources':'available by immutable original payload references'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    checks=[{'path':p.relative_to(out).as_posix(),'sha256':sha(p.read_bytes()),'size':p.stat().st_size}
            for p in sorted(out.rglob('*')) if p.is_file()]
    (out/'checksums.json').write_text(json.dumps(checks,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)

if __name__=='__main__':main()
