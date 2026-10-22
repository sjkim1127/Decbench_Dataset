import json
import unittest
from pathlib import Path

from decbench_dataset.manifest import ManifestError, compute_build_id
from decbench_dataset.matrix import expand_matrix, load_json, validate_matrix


ROOT = Path(__file__).resolve().parents[1]


class MatrixTests(unittest.TestCase):
    def test_foundation_matrix_validates(self) -> None:
        matrix = load_json(ROOT / "configs" / "build-matrix.json")
        toolchains = load_json(ROOT / "configs" / "toolchains.json")
        self.assertEqual(validate_matrix(matrix, toolchains), [])

    def test_variant_ids_are_stable_and_unique(self) -> None:
        matrix = load_json(ROOT / "configs" / "build-matrix.json")
        variants = list(expand_matrix(matrix, language="cpp"))
        ids = [v.variant_id for v in variants]
        self.assertTrue(ids)
        self.assertEqual(len(ids), len(set(ids)))
        variants2 = list(expand_matrix(matrix, language="cpp"))
        self.assertEqual(ids, [v.variant_id for v in variants2])

    def test_build_id_requires_exact_toolchain_version(self) -> None:
        manifest = {
            "project": "example",
            "language": "cpp",
            "source": {
                "repository_url": "https://example.invalid/repo.git",
                "commit_sha": "0123456789abcdef",
                "tree_hash": "treehash",
            },
            "target": {"id": "linux-x86_64-elf", "triple": "x86_64-unknown-linux-gnu"},
            "toolchain": {"family": "clang", "version_raw": ""},
            "profile": {"id": "O2", "opt": "O2"},
            "commands": ["clang++ ..."],
        }
        with self.assertRaises(ManifestError):
            compute_build_id(manifest)

        manifest["toolchain"]["version_raw"] = "verified-version-string"
        first = compute_build_id(manifest)
        second = compute_build_id(json.loads(json.dumps(manifest)))
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)


if __name__ == "__main__":
    unittest.main()
