import copy
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('publish_native',ROOT/'scripts/publish_native.py')
publisher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class NativeIdentityTests(unittest.TestCase):
    def test_windows_replays_share_identity_but_compiler_flags_and_env_do_not(self):
        row={'source':{'commit_sha':'a'*40,'snapshot_path':'source.tar'},
             'target':{'os':'windows','arch':'x86_64'},'project':'p','profile':'O2',
             'toolchain':{'sha256':'b'*64},'collector_sha256':'c'*64,'host':{},
             'environment':{'CL':'/DTEST=1'},
             'commands':[{'cwd':r'D:\corpus\sources\p','argv':['cl','/O2',r'/FoD:\corpus\builds\p\O2\1\unit.obj']}]}
        original=publisher.build_key(row)
        replay=copy.deepcopy(row)
        replay['commands'][0]['argv'][2]=r'/FoD:\corpus\builds\p\O2\2\unit.obj'
        self.assertEqual(original,publisher.build_key(replay))
        changed=copy.deepcopy(row);changed['environment']['CL']='/DTEST=2'
        self.assertNotEqual(original,publisher.build_key(changed))
        changed=copy.deepcopy(row);changed['commands'][0]['argv'][1]='/Od'
        self.assertNotEqual(original,publisher.build_key(changed))
