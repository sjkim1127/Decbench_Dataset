import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('macos_matrix',ROOT/'scripts/collect_macos_matrix.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class MacOSMatrixTests(unittest.TestCase):
    def test_lto_and_noinline_are_explicit_compiler_commands(self):
        project={'source_file':'original.cpp','language':'cpp','standard':'c++11'}
        source=Path('/source');out=Path('/out')
        commands=module.native_commands('macos','aarch64','clang++',project,'O2-ThinLTO',source,out)
        self.assertIn('-flto=thin',commands[0]);self.assertIn('-flto=thin',commands[1])
        self.assertIn('arm64',commands[0]);self.assertIn('arm64',commands[1])
        noinline=module.native_commands('macos','x86_64','clang++',project,'O2-noinline',source,out)
        self.assertIn('-fno-inline',noinline[0]);self.assertIn('-O2',noinline[0])


if __name__=='__main__':unittest.main()
