"""Run only inside the pinned pilot builder. Does not execute corpus code."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def probe(argv):
    p = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    return {"argv": argv, "returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr}


def main():
    recipe = json.loads(Path('/recipe.json').read_text())
    project = recipe['project']
    out = Path('/out')
    compiler = shutil.which(project['compiler'])
    tools = {}
    for name in (project['compiler'], 'ld', 'as', 'objcopy', 'readelf', 'strip'):
        executable = Path(shutil.which(name)).resolve()
        tools[name] = {"executable": str(executable), "executable_sha256": digest(executable),
                       "version": probe([str(executable), '--version'])}
    target = probe([compiler, '-dumpmachine'])['stdout'].strip()
    commands = []

    def run(argv, name, *, cwd='/src'):
        p = subprocess.run(argv, cwd=cwd, capture_output=True, timeout=1200)
        (out / (name + '.stdout')).write_bytes(p.stdout)
        (out / (name + '.stderr')).write_bytes(p.stderr)
        commands.append({"argv": argv, "cwd": cwd, "returncode": p.returncode,
                         "stdout_path": name + '.stdout', "stderr_path": name + '.stderr'})
        if p.returncode:
            raise RuntimeError(f'{name} failed: {p.returncode}')

    flags = ['-std=' + project['standard'], *recipe['flags'], '-g3', '-gdwarf-4',
             '-fPIC', '-march=x86-64', '-mtune=generic', '-frandom-seed=decbench',
             '-ffile-prefix-map=/src=SOURCE', '-fdebug-prefix-map=/src=SOURCE', '-v']
    status = 'success'
    error = None
    try:
        run([compiler, *flags, '-c', '/src/' + project['source_file'], '-o', '/out/unit.o'], 'compile')
        run([compiler, '-v', '-shared', '/out/unit.o', '-Wl,--build-id=sha1', '-o', '/out/binary.unstripped.so'], 'link')
        run(['objcopy', '--only-keep-debug', '/out/binary.unstripped.so', '/out/binary.debug'], 'split-debug')
        run(['objcopy', '--strip-debug', '--strip-unneeded', '/out/binary.unstripped.so', '/out/binary.stripped.so'], 'strip')
        run(['objcopy', '--add-gnu-debuglink=binary.debug', 'binary.stripped.so'], 'debuglink', cwd='/out')
        run(['readelf', '-aW', '/out/binary.unstripped.so'], 'elf')
        run(['readelf', '--debug-dump=info', '--debug-dump=decodedline', '/out/binary.unstripped.so'], 'dwarf')
        run(['readelf', '-aW', '/out/binary.stripped.so'], 'elf-stripped')
    except Exception as exc:
        status, error = 'failed', str(exc)
    report = {
        'status': status, 'error': error, 'tools': tools, 'commands': commands,
        'target_triple_observed': target,
        'compiler_probes': {key: probe([compiler, *args]) for key, args in {
            'configuration': ['-v'], 'sysroot': ['-print-sysroot'],
            'search_dirs': ['-print-search-dirs'], 'effective_options': [*flags, '-Q', '--help=target'],
            'optimizer_options': [*flags, '-Q', '--help=optimizers'],
            'predefined_macros': ['-dM', '-E', '-x', 'c++' if project['language']=='cpp' else 'c', '/dev/null']
        }.items()},
        'runner': {'os_release': Path('/etc/os-release').read_text(),
                   'kernel': platform.release(), 'machine': platform.machine(),
                   'libc': probe(['ldd', '--version']), 'packages': probe(['dpkg-query', '-W']),
                   'cpu': Path('/proc/cpuinfo').read_text()},
        'environment': dict(os.environ),
        'capture': {'driver_argv': 'complete', 'driver_subcommands': 'gcc-verbose-logs',
                    'execve_trace': 'not-collected', 'response_files': 'none-in-direct-recipe',
                    'produced_program_execution': False},
    }
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return 0 if status == 'success' else 1


if __name__ == '__main__':
    sys.exit(main())
