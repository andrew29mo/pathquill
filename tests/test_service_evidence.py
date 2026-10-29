import copy
import unittest
from tools.service_evidence import rate_limit_proof

class ServiceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.boot='12345678-1234-1234-1234-123456789abc';self.unit='pathquill.service'
        base=dict(_PID='1',UNIT=self.unit,_BOOT_ID=self.boot.replace('-',''),__MONOTONIC_TIMESTAMP='101')
        self.records=[dict(base,MESSAGE='Started '+self.unit+' - recorder.') for _ in range(3)]+[dict(base,MESSAGE=self.unit+': Start request repeated too quickly.')]
    def test_same_boot_uuid_representations_are_equivalent(self):
        proof=rate_limit_proof(self.records,self.unit,self.boot,100,3)
        self.assertEqual(proof,dict(actual_started_events=3,current_boot_pid1_limit_event=True))
    def test_old_foreign_incomplete_or_application_logs_never_pass(self):
        cases=[]
        for key,value in [('_PID','42'),('UNIT','foreign.service'),('_BOOT_ID','87654321-1234-1234-1234-123456789abc'),('__MONOTONIC_TIMESTAMP','99'),('__MONOTONIC_TIMESTAMP','bad')]:
            entries=copy.deepcopy(self.records)
            for entry in entries:entry[key]=value
            cases.append(entries)
        cases.extend([self.records[:-1],self.records[1:],self.records+[self.records[0]]])
        for entries in cases:
            with self.subTest(entries=entries):
                with self.assertRaises(ValueError):rate_limit_proof(entries,self.unit,self.boot,100,3)
    def test_sealed_receipt_requires_same_invocation_and_current_manager_start(self):
        import json
        from tools.service_evidence import sealed_exit_proof
        invocation='12345678123412341234123456789abc'
        manager=dict(self.records[0]);message=dict(manager);message.pop('UNIT');message.update(_PID='42',_SYSTEMD_UNIT=self.unit,_SYSTEMD_INVOCATION_ID=invocation,MESSAGE='store_sealed')
        stop=dict(message,MESSAGE=json.dumps(dict(schema='pathquill-service-exit-v1',result='success',code='exited',status='78',invocation=invocation)))
        records=[manager,message,stop]
        self.assertTrue(sealed_exit_proof(records,self.unit,self.boot,100)['matching_invocation_exit_receipt'])
        for bad in [records[:-1],records[1:],records+[manager],[manager,dict(message,_SYSTEMD_INVOCATION_ID='87654321123412341234123456789abc'),stop]]:
            with self.assertRaises(ValueError):sealed_exit_proof(bad,self.unit,self.boot,100)
