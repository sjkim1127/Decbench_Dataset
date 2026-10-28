import json
import unittest

from decbench_dataset.views import (config_specs, describe, metadata_file,
                                   normalize, project_identity, repository_path, update_card)


class CatalogViewsTests(unittest.TestCase):
    def row(self, **kwargs):
        return dict(build_id='build', project='upstream', language='rust', arch='arm64',
                    os='linux', format='elf', status='success', qualified=False,
                    payload_shard='payloads/upstream.tar', attempt=1,
                    manifest_json=json.dumps({'commit_sha': 'a' * 40}), **kwargs)

    def test_uses_target_architecture_and_preserves_all_original_evidence(self):
        row = self.row()
        manifest = {'host': {'arch': 'x86_64'}, 'target': {'arch': 'aarch64'},
                    'commands': [['rustc', '-C', 'opt-level=2']]}
        row['manifest_json'] = json.dumps(manifest)
        result = normalize(row, 'rust/campaign/data/attempts.parquet', 0, 'owner/data', 'revision')
        self.assertEqual(result['arch'], 'aarch64')
        self.assertEqual(json.loads(result['original_metadata_json']), row)
        self.assertEqual(result['manifest_json'], row['manifest_json'])
        self.assertEqual(result['payload_repo_path'], 'rust/campaign/payloads/upstream.tar')

    def test_replay_rows_and_failures_are_not_miscounted_as_unique_products(self):
        pilot = self.row()
        pilot['manifest_json'] = json.dumps({'reproducibility': {'replay_paths': ['1', '2']}})
        pilot = normalize(pilot, 'data/builds.parquet', 0, 'r', 's')
        failed = self.row()
        failed['status'] = 'failed'
        failed = normalize(failed, 'rust/c/data/attempts.parquet', 0, 'r', 's')
        summary = describe([pilot, failed])
        self.assertEqual(summary['records'], 2)
        self.assertEqual(summary['physical_attempts'], 3)
        self.assertEqual(summary['failed_records'], 1)
        self.assertEqual(summary['build_ids'], 1)

    def test_catalog_never_reimports_its_own_partitions(self):
        self.assertFalse(metadata_file('views/data/aarch64/rust.parquet'))
        self.assertTrue(metadata_file('opensource/batch/data/zig/attempts.parquet'))
        self.assertTrue(metadata_file('obfuscated/campaign/builds.parquet'))

    def test_card_refresh_preserves_original_configs_and_is_idempotent(self):
        card = '---\nconfigs:\n- config_name: builds\n  data_files:\n  - split: raw\n    path: data/*.parquet\n---\n# Corpus\n'
        rows = [normalize(self.row(), 'rust/c/data/attempts.parquet', 0, 'r', 's')]
        specs = config_specs(rows)
        updated = update_card(card, specs, 's')
        self.assertEqual(update_card(updated, specs, 's'), updated)
        self.assertIn('config_name: builds\n', updated)
        self.assertEqual(updated.count('config_name: language_rust\n'), 1)
        self.assertIn('path: views/data/aarch64/*.parquet', updated)

    def test_refuses_traversal_and_unknown_architecture(self):
        with self.assertRaises(ValueError):
            repository_path('native/campaign', '../escape.tar')
        row = self.row()
        row['arch'] = 'mystery'
        with self.assertRaises(ValueError):
            normalize(row, 'rust/c/data/a.parquet', 0, 'r', 's')

    def test_compiler_dimensions_use_evidence_and_target_not_host(self):
        row = self.row()
        row['arch'] = 'armv7'
        row['manifest_json'] = json.dumps({'target':{'arch':'armv7','triple':'arm-linux-gnueabihf','isa_mode':'thumb'},
            'toolchain':{'family':'clang','driver':{'stdout':'Ubuntu clang version 18.1.3\n'}}})
        result = normalize(row, 'native/c/data/attempts.parquet', 0, 'r', 's')
        self.assertEqual((result['arch'],result['isa_mode'],result['compiler_family'],result['compiler_version']),
                         ('armv7','thumb','clang','18.1.3'))
        self.assertIsNone(result['stdlib_family'])
        self.assertIsNone(result['libc_family'])

    def test_riscv_and_arm_have_distinct_architecture_configs(self):
        first, second = self.row(), self.row()
        first['arch'], second['arch'] = 'armv7', 'riscv64'
        rows = [normalize(first, 'native/c/data/attempts.parquet', 0, 'r', 's'),
                normalize(second, 'native/c/data/attempts.parquet', 1, 'r', 's')]
        specs = dict(config_specs(rows))
        self.assertEqual(specs['architecture_riscv64'], 'views/data/riscv64/*.parquet')
        self.assertEqual(specs['architecture_armv7'], 'views/data/armv7/*.parquet')

    def test_explicit_windows_target_survives_and_evidence_card_is_idempotent(self):
        row = self.row()
        row['manifest_json'] = json.dumps({'commands':[{'argv':['clang-cl','--target=aarch64-pc-windows-msvc']}]})
        result = normalize(row, 'native/c/data/attempts.parquet', 0, 'r', 's')
        self.assertEqual(result['compiler_target'], 'aarch64-pc-windows-msvc')
        card = '---\nconfigs:\n- config_name: builds\n  data_files:\n  - split: raw\n    path: data/*.parquet\n---\n# Corpus\n'
        specs = config_specs([result])
        updated = update_card(card, specs, 's', windows_pdb_evidence=True, qualification_pilot=True)
        self.assertEqual(update_card(updated, specs, 's', windows_pdb_evidence=True, qualification_pilot=True), updated)
        self.assertIn('views/evidence/windows-pdb-verification.parquet', updated)
        self.assertIn('views/evidence/qualification-candidates-cjson.parquet', updated)

    def test_project_revision_ids_are_stable_but_family_is_not_guessed(self):
        a, ar = project_identity('https://github.com/Example/Project.git', 'a'*40)
        b, br = project_identity('https://github.com/example/project', 'a'*40)
        c, cr = project_identity('https://github.com/example/project', 'b'*40)
        self.assertEqual((a, ar), (b, br))
        self.assertEqual(a, c)
        self.assertNotEqual(ar, cr)
        row = normalize(self.row(), 'native/c/data/attempts.parquet', 0, 'r', 's')
        self.assertIsNone(row['family_id'])
        self.assertEqual(row['family_id_status'], 'unreviewed')

    def test_derived_binary_is_not_counted_as_a_new_build_attempt(self):
        row=self.row()
        row['manifest_json']=json.dumps({'derivation':{'source_dataset_revision':'a'*40},'track':'pe-debug-directory-free'})
        result=normalize(row,'native/c/data/attempts.parquet',0,'r','s')
        self.assertEqual(result['row_grain'],'derived-binary')
        self.assertEqual(result['physical_attempt_count'],0)
        self.assertEqual(result['track'],'pe-debug-directory-free')


if __name__ == '__main__':
    unittest.main()
