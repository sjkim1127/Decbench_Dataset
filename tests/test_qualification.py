import copy
import json
from pathlib import Path
import unittest

import jsonschema


class QualificationGateTests(unittest.TestCase):
    def test_claimed_qualification_requires_independent_evidence(self):
        schema = json.loads((Path(__file__).resolve().parents[1]/'schemas/qualification-record.schema.json').read_text())
        row = {'schema_version':'qualification-0.1.0','binary_sha256':'a'*64,'debug_sha256':'b'*64,
               'source_commit':'c'*40,'source_function_id':None,'binary_function_va':42,'binary_function_size':8,
               'source_path':'source.c','source_line_start':10,'source_line_end':12,'inlined':None,
               'outlined':None,'compiler_generated':None,'mapping_method':'dwarf+symbol',
               'mapping_evidence':{},'oracle_status':'candidate','oracle_confidence':None,
               'qualification_reason':'independent gates not checked','qualified':False,
               'eligibility_gates':{'debug_association_verified':True,'source_body_extracted':True,
                 'boundary_independently_verified':False,'unique_mapping_verified':False,
                 'transformations_reviewed':False,'semantic_oracle_verified':False}}
        jsonschema.validate(row,schema)
        bad=copy.deepcopy(row);bad['qualified']=True;bad['oracle_status']='qualified'
        with self.assertRaises(jsonschema.ValidationError):jsonschema.validate(bad,schema)


if __name__ == '__main__': unittest.main()
