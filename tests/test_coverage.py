import json
from pathlib import Path
import unittest
from decbench_dataset.coverage import target_quotas


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.policy=json.loads((Path(__file__).parents[1]/'configs/coverage-policy.json').read_text())

    def test_quota_denominator_and_formats(self):
        for budget in (0,1,7,100,10000):
            rows=target_quotas(self.policy,budget)
            self.assertEqual(sum(r['target_builds'] for r in rows),budget)
            self.assertEqual(len(rows),9)
            for row in rows:
                self.assertGreaterEqual(row['target_builds'],0)
                self.assertEqual(row['format'],self.policy['format_by_os'][row['os']])
        rows=target_quotas(self.policy,10000)
        self.assertEqual({o:sum(r['target_builds'] for r in rows if r['os']==o) for o in self.policy['os_weights']},
                         {'linux':4000,'windows':3500,'macos':2500})

    def test_bad_policy_refused(self):
        self.policy['arch_weights_within_os']['macos']['x86_64']=41
        with self.assertRaises(ValueError): target_quotas(self.policy,100)
