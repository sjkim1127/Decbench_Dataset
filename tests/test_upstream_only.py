import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('upstream_sources',ROOT/'scripts/upstream_sources.py')
upstream=importlib.util.module_from_spec(spec);spec.loader.exec_module(upstream)


class UpstreamOnlyTests(unittest.TestCase):
    def test_authored_programs_and_harnesses_cannot_be_admitted(self):
        reviewed=json.loads((ROOT/'configs/additional-language-projects.json').read_text())['projects'][0]
        upstream.admit(reviewed)
        for key,value in [('source_origin','synthetic-fixture'),('dataset_authored_program_source',True),
                          ('collector_supplied_harness',True),('commit_sha','main'),('license_sha256','')]:
            invalid=copy.deepcopy(reviewed);invalid[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):upstream.admit(invalid)

    def test_modified_program_body_is_rejected(self):
        # Tooling-only negative test; temporary bytes are never corpus inputs.
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'upstream.swift';path.write_bytes(b'original upstream bytes')
            provenance={'tracked_files':{'upstream.swift':upstream.sha(path)}}
            self.assertTrue(upstream.verify_program_sources(directory,provenance)['original_program_sources_unchanged'])
            path.write_bytes(b'changed program body')
            with self.assertRaises(ValueError):upstream.verify_program_sources(directory,provenance)
