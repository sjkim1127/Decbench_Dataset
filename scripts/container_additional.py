"""Compile original Fortran/D/Nim products offline; never run corpus products."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from upstream_sources import sha,verify_program_sources


def run(argv,cwd=None):
    p=subprocess.run([str(x) for x in argv],cwd=cwd,capture_output=True,text=True,timeout=2400)
    return {'argv':[str(x) for x in argv],'cwd':str(cwd or Path.cwd()),'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}


recipe=json.loads(Path('/recipe.json').read_text());project=recipe['project'];opt=recipe['opt'];out=Path('/out')
source=out/'upstream';shutil.copytree('/src',source,ignore=shutil.ignore_patterns('.git'))
provenance=json.loads(Path('/provenance.json').read_text())
os.environ.update({'LC_ALL':'C','TZ':'UTC','SOURCE_DATE_EPOCH':'0','HOME':'/out/home'})
compiler={'fortran':'gfortran','d':'ldc2','nim':'nim'}[project['language']]
tools={}
for name in (compiler,'cc','ld','objcopy','readelf','cmake','ninja'):
    path=shutil.which(name)
    if path:tools[name]={'path':path,'executable_sha256':sha(Path(path).resolve()),'version':run([name,'--version'])}
report={'schema_version':'opensource-0.1.0','project':project,'profile':'opt'+opt,'commands':[],
        'tools':tools,'environment':dict(os.environ),'os_release':Path('/etc/os-release').read_text(),
        'package_manifest':Path('/toolchain-packages.txt').read_text(),'final_program_execution':False,
        'build_tools_execution':'upstream-build-system-and-compiler-tools-only','status':'success'}


def execute(argv,cwd=source):
    r=run(argv,cwd);name='command-'+str(len(report['commands']))
    (out/(name+'.stdout')).write_text(r.pop('stdout'));(out/(name+'.stderr')).write_text(r.pop('stderr'))
    r.update({'stdout_path':name+'.stdout','stderr_path':name+'.stderr'});report['commands'].append(r)
    if r['returncode']:raise RuntimeError(name+' failed')


try:
    if project['language']=='d':
        execute(['ldc2','-O'+opt,'-g','-v','-I'+str(source),'-of='+str(out/'binary.unstripped'),
                 source/'dustmite.d',source/'polyhash.d',source/'splitter.d'])
    elif project['language']=='nim':
        execute(['nim','c','--nimcache:'+str(out/'nimcache'),'--debugger:native','--lineDir:on','--listCmd',
                 '--opt:'+('none' if opt=='0' else 'speed'),'--passC:-O'+opt,'--passC:-g',
                 *(['--path:/deps/nim'] if Path('/deps/nim').exists() else []),
                 '--out:'+str(out/'binary.unstripped'),source/'src/nimble.nim'])
    else:
        execute(['cmake','-S',source,'-B',out/'cmake-build','-G','Ninja',
                 '-DCMAKE_BUILD_TYPE=Debug','-DCMAKE_Fortran_FLAGS_DEBUG=-O'+opt+' -g',
                 '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON','-DJSONFORTRAN_ENABLE_TESTS=OFF',
                 '-DJSONFORTRAN_ENABLE_DOC_GENERATION=OFF','-DJSONFORTRAN_STATIC_LIBRARY_ONLY=OFF'])
        execute(['cmake','--build',out/'cmake-build','--parallel','2','--verbose'])
        binaries=[p for p in (out/'cmake-build').rglob('libjsonfortran.so*') if p.is_file() and not p.is_symlink()]
        if len(binaries)!=1:raise ValueError('Expected one original JSON-Fortran shared-library product: '+str(binaries))
        shutil.copyfile(binaries[0],out/'binary.unstripped')
    report['source_integrity']=verify_program_sources(source,provenance)
    for argv in (['objcopy','--only-keep-debug',out/'binary.unstripped',out/'binary.debug'],
                 ['objcopy','--strip-debug','--strip-unneeded',out/'binary.unstripped',out/'binary.stripped'],
                 ['objcopy','--add-gnu-debuglink='+str(out/'binary.debug'),out/'binary.stripped'],
                 ['readelf','-aW',out/'binary.unstripped']):execute(argv,cwd=out)
except Exception as exc:
    report['status']='failed';report['error']=str(exc)
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
raise SystemExit(int(report['status']!='success'))
