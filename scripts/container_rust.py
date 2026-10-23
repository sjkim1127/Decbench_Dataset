"""Offline Cargo compiler driver; final corpus CLIs are never executed."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(argv):
    p=subprocess.run(argv,cwd='/src',capture_output=True,text=True,timeout=2400)
    return {'argv':argv,'cwd':'/src','returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}


recipe=json.loads(Path('/recipe.json').read_text());out=Path('/out')
env={'CARGO_HOME':'/out/cargo-home','CARGO_TARGET_DIR':'/out/target','RUSTUP_TOOLCHAIN':'1.99.1',
     'CARGO_PROFILE_RELEASE_OPT_LEVEL':recipe['opt'],'CARGO_PROFILE_RELEASE_DEBUG':'2',
     'CARGO_PROFILE_RELEASE_STRIP':'none','CARGO_PROFILE_RELEASE_LTO':'false',
     'CARGO_PROFILE_RELEASE_CODEGEN_UNITS':'1','CARGO_PROFILE_RELEASE_INCREMENTAL':'false',
     'CARGO_PROFILE_RELEASE_PANIC':'unwind','CARGO_PROFILE_RELEASE_OVERFLOW_CHECKS':'false',
     'RUSTFLAGS':'--remap-path-prefix=/src=SOURCE --remap-path-prefix=/out=BUILD --remap-path-prefix=/vendor=VENDOR',
     'SOURCE_DATE_EPOCH':'0','TZ':'UTC','LC_ALL':'C'}
os.environ.update(env)
commands=[]
actual_tools={n:run(['rustup','which',n])['stdout'].strip() for n in ('rustc','cargo')}
report={'schema_version':'cargo-0.1.0','environment':env,'commands':commands,
        'compiler':{n:{'path':shutil.which(n),'resolved_sha256':sha(Path(shutil.which(n)).resolve()),
                       'version':run([n,*(['-vV'] if n=='rustc' else ['--version'])])}
                    for n in ('rustc','cargo','cc','ld','objcopy','readelf')},
        'actual_toolchain_binaries':{n:{'path':path,'sha256':sha(path)} for n,path in actual_tools.items()},
        'target_cfg':run(['rustc','--print','cfg']),
        'os_release':Path('/etc/os-release').read_text(),
        'libc':run(['ldd','--version']), 'kernel':run(['uname','-a']),
        'package_manifest':run(['dpkg-query','-W']),
        'build_scripts':'executed-in-offline-resource-limited-container',
        'corpus_cli_execution':False,'status':'success'}
try:
    result=run(['cargo','--config','/config/vendor.toml','build','--release','--frozen',
                '--bin',recipe['binary'],'--message-format=json-render-diagnostics','-vv','-j','2'])
    (out/'cargo.stdout').write_text(result.pop('stdout'));(out/'cargo.stderr').write_text(result.pop('stderr'))
    result.update({'stdout_path':'cargo.stdout','stderr_path':'cargo.stderr'});commands.append(result)
    if result['returncode']:raise RuntimeError('cargo build failed')
    shutil.copyfile(out/'target/release'/recipe['binary'],out/'binary.unstripped')
    for argv,name in [(['objcopy','--only-keep-debug','/out/binary.unstripped','/out/binary.debug'],'split-debug'),
                      (['objcopy','--strip-debug','--strip-unneeded','/out/binary.unstripped','/out/binary.stripped'],'strip'),
                      (['objcopy','--add-gnu-debuglink=/out/binary.debug','/out/binary.stripped'],'debuglink'),
                      (['readelf','-aW','/out/binary.unstripped'],'elf')]:
        r=run(argv);(out/(name+'.stdout')).write_text(r.pop('stdout'));(out/(name+'.stderr')).write_text(r.pop('stderr'))
        r.update({'stdout_path':name+'.stdout','stderr_path':name+'.stderr'});commands.append(r)
        if r['returncode']:raise RuntimeError(name+' failed')
except Exception as exc:
    report['status']='failed';report['error']=str(exc)
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
raise SystemExit(int(report['status']!='success'))
