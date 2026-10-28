import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('windows_matrix',ROOT/'scripts/collect_windows_matrix.py')
module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class WindowsMatrixTests(unittest.TestCase):
    def test_msvc_size_and_clang_o1_have_distinct_options(self):
        project={'source_file':'src.cpp','language':'cpp','standard':'c++11'}
        clang=module.native_commands('windows','aarch64','clang-cl',project,'O1',Path('/source'),Path('/build'),'clang-cl')
        msvc=module.native_commands('windows','aarch64','cl',project,'Osize-msvc',Path('/source'),Path('/build'),'msvc')
        self.assertIn('/clang:-O1',clang[0])
        self.assertIn('--target=aarch64-pc-windows-msvc',clang[0])
        self.assertIn('/O1',msvc[0])
        self.assertNotIn('/clang:-O1',msvc[0])


if __name__ == '__main__': unittest.main()
