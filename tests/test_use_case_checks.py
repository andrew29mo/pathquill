import copy,json,unittest
from pathquill.publication import package_bodies
from tools.use_case_checks import verify_package

class PublicExampleChecks(unittest.TestCase):
    def snapshot(self):
        rows=[dict(order=1,kind='tcp',outcome='refused',relative_seconds=-.01),dict(order=2,kind='tcp',outcome='success',relative_seconds=1)]
        for group,state in [('links',dict(interface='interface_1',name='name_1',mac='mac_1')),('addresses',dict(interface='interface_1',address='ip_1',family=4,prefix=24)),('routes',dict(interface='interface_1',destination='ip_2',family=4,prefix=24))]:rows.append(dict(order=len(rows)+1,kind='state_object',group=group,state=state,relative_seconds=-1))
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

    def test_unicode_encoded_canary_is_rejected(self):
        snapshot=self.snapshot();snapshot['leak']='pqprivate0'
        encoded=json.dumps(snapshot).replace('pqprivate0',r'\u0070qprivate0')
        with self.assertRaisesRegex(ValueError,'sensitive_value'):verify_package(package_bodies(encoded),['pqprivate0'])
    def test_route_raw_value_and_empty_context_refused(self):
        snapshot=self.snapshot();snapshot['observations'][-1]['state']['destination']='198.19.0.0'
        with self.assertRaisesRegex(ValueError,'sensitive_value'):verify_package(package_bodies(json.dumps(snapshot)),['198.19.0.0'])
        for group in ('links','routes'):
            snapshot=self.snapshot()
            for r in snapshot['observations']:
                if r.get('group')==group:r['state']={}
            with self.subTest(group=group),self.assertRaises(ValueError):verify_package(package_bodies(json.dumps(snapshot)),[])
    def test_valid_hash_html_trailer_is_rejected(self):
        import hashlib
        files=package_bodies(json.dumps(self.snapshot()));files['index.html']+=b'<script>alert(1)</script>'
        m=json.loads(files['manifest.json']);m['files']['index.html']=dict(bytes=len(files['index.html']),sha256=hashlib.sha256(files['index.html']).hexdigest());files['manifest.json']=json.dumps(m).encode()
        with self.assertRaisesRegex(ValueError,'html_snapshot_mismatch'):verify_package(files,[])
    def test_cleanup_only_failure_is_retained(self):
        from tools.use_case_checks import retain_attempt
        self.assertTrue(retain_attempt(dict(passed=False,cleanup_error='busy')))
        self.assertTrue(retain_attempt(dict(passed=False,error='failed')))
        self.assertFalse(retain_attempt(dict(passed=False,status='in_progress')))
        self.assertFalse(retain_attempt(dict(passed=True)))
    def test_private_outputs_follow_checkout_owner_1000(self):
        import os,pathlib,tempfile,subprocess,sys
        from tools.use_case_checks import private_outputs
        if os.geteuid()!=0 or sys.platform!='linux':self.skipTest('requires root in isolated Linux VM')
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);os.chown(root,1000,1000)
            work,trace,owner=private_outputs(root)
            self.assertEqual(owner,(1000,1000));self.assertEqual(work.stat().st_mode&0o777,0o700);self.assertEqual(trace.stat().st_mode&0o777,0o600)
            self.assertEqual(trace.stat().st_uid,1000)
            def execute(uid):
                def drop():os.setgroups([]);os.setgid(uid);os.setuid(uid)
                return subprocess.run([sys.executable,'-c','import sys;open(sys.argv[1]).read()',str(trace)],preexec_fn=drop,capture_output=True).returncode
            self.assertEqual(execute(1000),0);self.assertNotEqual(execute(501),0)
