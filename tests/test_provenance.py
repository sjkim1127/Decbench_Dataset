import copy
import unittest

from decbench_dataset.manifest import compute_build_id
from decbench_dataset.matrix import expand_matrix
import test_matrix


class ProvenanceTests(unittest.TestCase):
    def test_build_identity_distinguishes_abi_sdk_and_options(self):
        base = {'project': 'p', 'language': 'cpp',
                'source': {'repository_url': 'https://example.invalid/p', 'commit_sha': 'a' * 40, 'tree_hash': 'b' * 40},
                'target': {'id': 'linux-x86_64', 'abi': 'sysv', 'sdk': 'a'},
                'toolchain': {'family': 'gcc', 'version_raw': 'test-compiler', 'executable_sha256': 'c' * 64},
                'profile': {'id': 'O2'}, 'commands': ['cc -O2 a.c'],
                'environment': {'CFLAGS': '-O2'}, 'runner': {'image_digest': 'sha256:abc'}}
        identity = compute_build_id(base)
        for section, key, value in [('target', 'abi', 'other'), ('target', 'sdk', 'b'),
                                    ('toolchain', 'executable_sha256', 'd' * 64),
                                    ('environment', 'CFLAGS', '-O3'), ('runner', 'image_digest', 'sha256:def')]:
            changed = copy.deepcopy(base)
            changed[section][key] = value
            with self.subTest(section=section, key=key):
                self.assertNotEqual(identity, compute_build_id(changed))
        changed = copy.deepcopy(base)
        changed['artifacts'] = [{'sha256': 'output'}]
        changed['runner']['cpu'] = 'volatile telemetry'
        self.assertEqual(identity, compute_build_id(changed))

    def test_all_nine_languages_and_profile_content_identity(self):
        fixture = test_matrix.MatrixTests()
        fixture.setUp()
        self.assertEqual(set(fixture.matrix['languages']), {'c', 'cpp', 'rust', 'go', 'zig', 'swift', 'fortran', 'd', 'nim'})
        for lang in fixture.matrix['languages']:
            self.assertTrue(list(expand_matrix(fixture.matrix, toolchains=fixture.toolchains, language=lang)))
        first = next(expand_matrix(fixture.matrix, toolchains=fixture.toolchains, language='c'))
        fixture.matrix['languages']['c']['profiles'][0]['extra_flag'] = '-fwrapv'
        second = next(expand_matrix(fixture.matrix, toolchains=fixture.toolchains, language='c'))
        self.assertNotEqual(first.variant_id, second.variant_id)


if __name__ == '__main__':
    unittest.main()
