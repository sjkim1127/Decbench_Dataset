"""Build the original upstream bc7enc CMake executable, without running it."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import zlib

OUT=Path('/out'); SOURCE=Path('/src'); PROFILE=os.environ['CORPUS_PROFILE']
environment={'PATH':'/usr/bin:/bin','HOME':'/tmp','LC_ALL':'C','SOURCE_DATE_EPOCH':'0'}

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def version(name):
    path=Path(shutil.which(name)).resolve()
    p=subprocess.run([str(path),'--version'],env=environment,capture_output=True,text=True)
    return {'path':str(path),'sha256':sha(path),'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}

tools={n:version(n) for n in ('gcc','g++','ld','cmake','ninja','objcopy','readelf')}
commands=[]

def execute(argv,cwd):
    n=len(commands); argv=[str(x) for x in argv]
    p=subprocess.run(argv,cwd=cwd,env=environment,capture_output=True,timeout=2400)
    (OUT/f'command-{n}.stdout').write_bytes(p.stdout)
    (OUT/f'command-{n}.stderr').write_bytes(p.stderr)
    commands.append({'argv':argv,'cwd':str(cwd),'returncode':p.returncode,
                     'stdout_path':f'command-{n}.stdout','stderr_path':f'command-{n}.stderr'})
    if p.returncode:raise RuntimeError(f'command {n} failed ({p.returncode})')

result={'status':'success','profile':PROFILE,'environment':environment,'tools':tools,
        'source_origin':'upstream-open-source','final_program_execution':False,'commands':commands}
try:
    # This upstream revision uses uint*_t in ert.h without including <cstdint>.
    # Supply the standard header as an explicit compiler option; never edit source.
    flags='-O2 -g -DNDEBUG -include cstdint'+(' -flto' if PROFILE=='O2-LTO' else '')
    execute(['cmake','-S',SOURCE,'-B',OUT/'cmake-build','-G','Ninja',
             '-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_FLAGS_RELEASE='+flags,
             '-DCMAKE_C_FLAGS_RELEASE='+flags,'-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
             '-DSUPPORT_BC7E=OFF'],OUT)
    execute(['cmake','--build',OUT/'cmake-build','--parallel','2','--verbose'],OUT)
    source_binary=OUT/'cmake-build/bc7enc'
    if not source_binary.is_file():raise ValueError('Original upstream CMake product missing')
    shutil.copyfile(source_binary,OUT/'binary.unstripped')
    h=(OUT/'binary.unstripped').read_bytes()[:64]
    if h[:4]!=b'\x7fELF' or h[4]!=2 or h[5]!=1 or struct.unpack_from('<H',h,18)[0]!=183:
        raise ValueError('Expected AArch64 ELF executable')
    for cmd in (['objcopy','--only-keep-debug','binary.unstripped','binary.debug'],
                ['objcopy','--strip-debug','--strip-unneeded','binary.unstripped','binary.stripped'],
                ['objcopy','--add-gnu-debuglink=binary.debug','binary.stripped'],
                ['objcopy','--dump-section','.gnu_debuglink=debuglink.bin','binary.stripped'],
                ['objcopy','--dump-section','.text=original.text','binary.unstripped'],
                ['objcopy','--dump-section','.text=stripped.text','binary.stripped'],
                ['readelf','-aW','binary.unstripped'],
                ['ninja','-C',OUT/'cmake-build','-t','commands']):execute(cmd,OUT)
    raw=(OUT/'debuglink.bin').read_bytes();n=raw.index(b'\0');pos=(n+4)&~3
    crc=struct.unpack_from('<I',raw,pos)[0]
    if raw[:n]!=b'binary.debug' or crc!=zlib.crc32((OUT/'binary.debug').read_bytes())&0xffffffff:
        raise ValueError('debuglink mismatch')
    if sha(OUT/'original.text')!=sha(OUT/'stripped.text'):
        raise ValueError('stripped .text mismatch')
    result['debug_relation']={'status':'debuglink-crc-matched','crc32':f'{crc:08x}',
                               'text_sha256':sha(OUT/'original.text')}
    for n in ('debuglink.bin','original.text','stripped.text'):(OUT/n).unlink()
    for n in ('compile_commands.json','CMakeCache.txt','build.ninja'):
        shutil.copyfile(OUT/'cmake-build'/n,OUT/n)
except Exception as exc:
    result['status']='failed';result['error']=str(exc)
(OUT/'report.json').write_text(json.dumps(result,indent=2)+'\n')
raise SystemExit(int(result['status']!='success'))
