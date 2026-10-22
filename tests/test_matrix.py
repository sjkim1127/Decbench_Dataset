import json
import unittest
from pathlib import Path

from decbench_dataset.extractors import contract_for_format
from decbench_dataset.manifest import ManifestError, compute_build_id
from decbench_dataset.matrix import expand_matrix, load_json, validate_matrix
from decbench_dataset.planner import ProjectSource, plan_jobs


ROOT = Path(__file__).resolve().parents[1]


class MatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.matrix = load_json(ROOT / "configs" / "build-matrix.json")
        self.toolchains = load_json(ROOT / "configs" / "toolchains.json")

    def test_foundation_matrix_validates(self) -> None:
        self.assertEqual(validate_matrix(self.matrix, self.toolchains), [])

    def test_variant_ids_are_stable_and_unique(self) -> None:
        variants = list(expand_matrix(self.matrix, toolchains=self.toolchains, language="cpp"))
        ids = [v.variant_id for v in variants]
        self.assertTrue(ids)
        self.assertEqual(len(ids), len(set(ids)))
        variants2 = list(expand_matrix(self.matrix, toolchains=self.toolchains, language="cpp"))
        self.assertEqual(ids, [v.variant_id for v in variants2])

    def test_compiler_format_capabilities_filter_impossible_targets(self) -> None:
        variants = list(expand_matrix(self.matrix, toolchains=self.toolchains, language="cpp"))
        msvc_targets = {v.target["format"] for v in variants if v.compiler_set == "msvc"}
        gcc_targets = {v.target["format"] for v in variants if v.compiler_set == "gcc"}
        self.assertEqual(msvc_targets, {"pe"})
        self.assertEqual(gcc_targets, {"elf"})

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

    def test_unresolved_toolchains_produce_no_concrete_jobs(self) -> None:
        variant = next(expand_matrix(self.matrix, toolchains=self.toolchains, language="cpp"))
        source = ProjectSource("example", "https://example.invalid/repo", "deadbeef", "treehash")
        self.assertEqual(list(plan_jobs(source, variant, self.toolchains)), [])

    def test_format_contracts_cover_all_primary_formats(self) -> None:
        for fmt in ("elf", "pe", "macho"):
            self.assertEqual(contract_for_format(fmt).format, fmt)


if __name__ == "__main__":
    unittest.main()
