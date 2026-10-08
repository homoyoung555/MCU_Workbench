from types import SimpleNamespace as Obj
import unittest

from gui.test_groups import copy_groups


class CopyGroupTests(unittest.TestCase):
    def test_canonical_boundaries_and_system_exclusion(self):
        def definition(identity,rows,recipe):
            return Obj(identity=identity,cp='CP3',item='Same_Name',flow_type='verify',typed_kind='DC_PARAMETRIC_TEST',
                       source_rows=rows,datalog_points=('high','low'),effective_recipe=recipe)
        definitions=[definition('BASE',(183,184),('DC_TEST',)),definition('SHMOO',(185,),('SHMOO',)),definition('SYSTEM',(),())]
        compilation=Obj(is_valid=True,plan=Obj(cp_plans={'CP3':Obj(definitions=definitions,schedule=[])},
                      catalogs=Obj(dc_parametric_plans={181:Obj(config_patterns=('PT104_Leakage',))})))
        editor=Obj(by_name={'FLOW':{'appendableRows':[183,184]}})
        groups=copy_groups(compilation,editor)
        self.assertEqual([g['rows'] for g in groups],[[183,184],[185]])
        self.assertTrue(groups[0]['copyable']);self.assertFalse(groups[1]['copyable'])
        self.assertEqual(groups[0]['patterns'],['PT104_Leakage'])
        self.assertEqual(groups[0]['id'],'BASE');self.assertEqual(groups[1]['id'],'SHMOO')

    def test_invalid_compilation_has_no_copy_plan(self):
        self.assertEqual(copy_groups(Obj(is_valid=False),Obj()),[])


if __name__=='__main__':unittest.main()
