import copy,json,unittest
from pathquill.publication import package_bodies
from tools.use_case_checks import verify_package

class PublicExampleChecks(unittest.TestCase):
    def snapshot(self):
        rows=[dict(order=1,kind='tcp',outcome='refused',relative_seconds=-.01),dict(order=2,kind='tcp',outcome='success',relative_seconds=1)]
        for group in ('links','addresses','routes'):rows.append(dict(order=len(rows)+1,kind='state_object',group=group,state=dict(address='ip_1'),relative_seconds=-1))
        return dict(schema='pathquill-snapshot-v1',incident=dict(state='SEALED',recovered=True,window_seconds=30,endpoints=['ip_1']),observations=rows)
    def test_real_package_contract_and_private_canary_rejected(self):
        snapshot=self.snapshot();files=package_bodies(json.dumps(snapshot))
        self.assertEqual(verify_package(files,['PRIVATE-CANARY'])['tcp']['outcomes'],dict(refused=1,success=1))
        snapshot['leak']='private-canary';files=package_bodies(json.dumps(snapshot))
        with self.assertRaisesRegex(ValueError,'sensitive_value'):verify_package(files,['PRIVATE-CANARY'])
    def test_valid_hashes_do_not_hide_missing_failure_or_state(self):
        for remove in ('tcp','state_object'):
            snapshot=self.snapshot();snapshot['observations']=[r for r in snapshot['observations'] if r['kind']!=remove]
            for i,row in enumerate(snapshot['observations'],1):row['order']=i
            with self.subTest(remove=remove),self.assertRaises(ValueError):verify_package(package_bodies(json.dumps(snapshot)),[])
    def test_mutated_html_or_manifest_refused(self):
        original=package_bodies(json.dumps(self.snapshot()))
        for name in ('index.html','manifest.json'):
            files=copy.deepcopy(original);files[name]+=b'corrupt'
            with self.subTest(name=name),self.assertRaises(ValueError):verify_package(files,[])
