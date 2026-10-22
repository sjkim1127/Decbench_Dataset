import unittest

from decbench_dataset.toolchain import ToolchainDiscoveryError, parse_version, version_command


class ToolchainTests(unittest.TestCase):
    def test_parse_version(self) -> None:
        self.assertEqual(parse_version("clang version 18.1.8"), (18, 1, 8))
        self.assertEqual(parse_version("go version go1.25.3 linux/amd64"), (1, 25, 3))
        self.assertEqual(parse_version("zig 0.15.1"), (0, 15, 1))
        self.assertEqual(parse_version("no numeric version"), (None, None, None))

    def test_version_commands(self) -> None:
        self.assertEqual(version_command("gcc", "/x/gcc"), ["/x/gcc", "--version"])
        self.assertEqual(version_command("rustc", "/x/rustc"), ["/x/rustc", "-Vv"])
        self.assertEqual(version_command("go", "/x/go"), ["/x/go", "version"])
        self.assertEqual(version_command("msvc", "cl.exe"), ["cl.exe"])
        with self.assertRaises(ToolchainDiscoveryError):
            version_command("unknown", "cc")


if __name__ == "__main__":
    unittest.main()
