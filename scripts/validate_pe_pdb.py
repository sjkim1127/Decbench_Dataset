"""Independently compare PE CodeView GUID/age, PDB identity and paired .text."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import uuid

ROOT=Path('/input');OUT=Path('/out')
OUT.mkdir(parents=True,exist_ok=True)

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def parse_pe(path):
    b=path.read_bytes()
    if b[:2]!=b'MZ':raise ValueError('Missing MZ signature')
    pe=struct.unpack_from('<I',b,0x3c)[0]
    if b[pe:pe+4]!=b'PE\0\0':raise ValueError('Missing PE signature')
    machine, count=struct.unpack_from('<HH',b,pe+4)
    optsize=struct.unpack_from('<H',b,pe+20)[0];opt=pe+24
    magic=struct.unpack_from('<H',b,opt)[0]
    directory=opt+({0x10b:96,0x20b:112}[magic]);sections=[]
    for i in range(count):
        off=opt+optsize+i*40;name=b[off:off+8].rstrip(b'\0').decode('ascii','replace')
        vsize,va,rawsize,rawptr=struct.unpack_from('<IIII',b,off+8)
        if rawptr+rawsize>len(b):raise ValueError('Truncated section')
        sections.append((name,va,vsize,rawptr,rawsize))
    texts=[(b[p:p+s],vs) for name,_,vs,p,s in sections if name=='.text']
    if len(texts)!=1:raise ValueError('Expected one .text section')
    debug_rva,debug_size=struct.unpack_from('<II',b,directory+6*8)
    debug=[]
    if debug_rva and debug_size:
        matches=[(p+debug_rva-va,rs-(debug_rva-va)) for _,va,vs,p,rs in sections
                 if va<=debug_rva<va+max(vs,rs) and debug_rva-va<rs]
        if len(matches)!=1:raise ValueError('Unmapped PE debug directory')
        debug_off,available=matches[0]
        if debug_size>available or debug_size%28:raise ValueError('Malformed PE debug directory')
        for off in range(debug_off,debug_off+debug_size,28):
            kind,size,_,rawptr=struct.unpack_from('<IIII',b,off+12)
            if kind==2 and rawptr+size<=len(b) and b[rawptr:rawptr+4]==b'RSDS' and size>=24:
                debug.append({'guid':str(uuid.UUID(bytes_le=b[rawptr+4:rawptr+20])),
                              'age':struct.unpack_from('<I',b,rawptr+20)[0]})
    raw,virtual_size=texts[0]
    virtual=raw[:virtual_size]+b'\0'*max(0,virtual_size-len(raw))
    return {'machine':machine,'text_sha256':hashlib.sha256(raw).hexdigest(),
            'text_size':len(raw),'virtual_text_sha256':hashlib.sha256(virtual).hexdigest(),
            'virtual_text_size':virtual_size,'codeview':debug}

rows=[]
for ledger in sorted(ROOT.rglob('attempts.jsonl')):
    root=ledger.parent
    for row in map(json.loads,ledger.read_text().splitlines()):
        if row['status']!='success':continue
        folder=root/'builds'/row['project']/row['profile']/str(row['attempt'])
        binary,pdb,stripped=(folder/n for n in ('binary.dll','binary.pdb','binary.stripped.dll'))
        result={'family':row['toolchain']['family'],'arch':row['target']['arch'],'project':row['project'],
                'profile':row['profile'],'attempt':row['attempt'],'binary_sha256':None,'pdb_sha256':None,
                'stripped_sha256':None,'association':'error','text_preserved':None}
        try:
            original,copy=parse_pe(binary),parse_pe(stripped)
            proc=subprocess.run(['llvm-pdbutil','dump','-summary',str(pdb)],capture_output=True,text=True,timeout=60)
            guid=re.search(r'^\s*GUID:\s*\{([^}]+)\}',proc.stdout,re.M)
            age=re.search(r'^\s*Age:\s*(\d+)',proc.stdout,re.M)
            if proc.returncode or not guid or not age:raise ValueError('PDB identity extraction failed')
            pdb_id={'guid':str(uuid.UUID(guid.group(1))), 'age':int(age.group(1))}
            result.update(binary_sha256=sha(binary),pdb_sha256=sha(pdb),stripped_sha256=sha(stripped),
                pe_codeview=original['codeview'], pdb_identity=pdb_id,
                stripped_codeview=copy['codeview'],
                association='matched' if len(original['codeview'])==1 and original['codeview'][0]==pdb_id else 'mismatch',
                text_preserved=original['text_sha256']==copy['text_sha256'] and original['text_size']==copy['text_size'],
                virtual_text_preserved=original['virtual_text_sha256']==copy['virtual_text_sha256'] and original['virtual_text_size']==copy['virtual_text_size'],
                original_text_sha256=original['text_sha256'],stripped_text_sha256=copy['text_sha256'],
                virtual_text_size=original['virtual_text_size'])
        except Exception as exc:
            result['error']=str(exc)
        rows.append(result)
(OUT/'windows-pdb-verification.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
summary={'records':len(rows),'association':dict(Counter(r['association'] for r in rows)),
         'text_preserved':dict(Counter(str(r['text_preserved']) for r in rows)),
         'virtual_text_preserved':dict(Counter(str(r.get('virtual_text_preserved')) for r in rows)),
         'stripped_codeview_retained':sum(bool(r.get('stripped_codeview')) for r in rows),
         'qualified':0,'input':'Windows CI run 40620095669','tool':'llvm-pdbutil',
         'limits':['CodeView GUID/age and .text only; not full debug or semantic qualification']}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2),flush=True)
