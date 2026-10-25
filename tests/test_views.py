import json
import unittest

from decbench_dataset.views import (config_specs, describe, metadata_file,
                                   normalize, repository_path, update_card)


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


if __name__ == '__main__':
    unittest.main()
