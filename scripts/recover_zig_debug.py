"""Retry unavailable Zig objcopy operations on the same original build artifacts."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
from upstream_sources import sha


def main():
    p=argparse.ArgumentParser();p.add_argument('corpus',type=Path);args=p.parse_args();root=args.corpus.resolve()
    ledger=root/'attempts.jsonl';original=ledger.read_bytes();rows=[json.loads(line) for line in original.decode().splitlines()]
    history=root/'postprocess-history';history.mkdir(exist_ok=False);(history/'attempts.before-recovery.jsonl').write_bytes(original)
    tool=Path(shutil.which('llvm-objcopy')).resolve()
    for row in rows:
        if row['status']=='success':continue
        if row['commands'][0]['returncode']!=0 or not row.get('source_integrity',{}).get('original_program_sources_unchanged'):
            continue
        out=root/'builds'/row['target']['triple']/row['profile']/str(row['attempt'])
        before=sha(out/'binary.unstripped')
        backup=history/row['target']['triple']/row['profile']/str(row['attempt']);backup.mkdir(parents=True)
        shutil.copyfile(out/'manifest.json',backup/'manifest.json')
        argv=[[str(tool),'--strip-debug',str(out/'binary.unstripped'),str(out/'binary.llvm.stripped')]]
        if row['target']['format']=='elf':
            argv.insert(0,[str(tool),'--only-keep-debug',str(out/'binary.unstripped'),str(out/'binary.llvm.debug')])
            argv.append([str(tool),'--add-gnu-debuglink='+str(out/'binary.llvm.debug'),str(out/'binary.llvm.stripped')])
        for command in argv:
            result=subprocess.run(command,capture_output=True,text=True,timeout=120)
            name='command-'+str(len(row['commands']));(out/(name+'.stdout')).write_text(result.stdout);(out/(name+'.stderr')).write_text(result.stderr)
            row['commands'].append({'argv':command,'cwd':str(out),'returncode':result.returncode,'stdout_path':name+'.stdout','stderr_path':name+'.stderr'})
            if result.returncode:raise RuntimeError('LLVM debug derivative recovery failed: '+result.stderr)
        if sha(out/'binary.unstripped')!=before:raise ValueError('Original upstream build artifact changed')
        row['initial_status']=row['status'];row['status']='success';row['recovered_error']=row.pop('error',None)
        row['artifact_recovery']={'kind':'postprocess-only-original-binary-unchanged','tool':str(tool),'sha256':sha(tool),
                                  'version':subprocess.run([tool,'--version'],capture_output=True,text=True,check=True).stdout,
                                  'history':str(backup.relative_to(root)),'original_binary_sha256':before}
        row['artifacts']=[{'path':f.relative_to(root).as_posix(),'sha256':sha(f),'size':f.stat().st_size} for f in sorted(out.iterdir()) if f.is_file() and f.name!='manifest.json']
        (out/'manifest.json').write_text(json.dumps(row,indent=2)+'\n')
        print(row['target']['triple'],row['profile'],row['attempt'],'debug derivative recovered',flush=True)
    ledger.write_text(''.join(json.dumps(r)+'\n' for r in rows))


if __name__=='__main__':main()
