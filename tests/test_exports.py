import json
import tempfile
import unittest
from pathquill.exports import ExportRecorder
from pathquill.core import Refused
class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.r=ExportRecorder(self.tmp.name)
        self.r.observe(dict(kind='state_object',group='links',value=dict(index=7,attributes={'3':b'SECRET-LINK\0'.hex(),'1':'aabbccddeeff'})),0)
        self.r.observe(dict(kind='state_object',group='addresses',value=dict(index=7,family=2,prefix=24,attributes={'1':'0a172d43'})),1)
        self.r.observe(dict(kind='state_object',group='routes',value=dict(family=2,dst_prefix=24,attributes={'1':'0a172d00','5':'0a172d43','4':'07000000'})),1.5)
        self.r.observe(dict(kind='tcp',outcome='refused',secret='<script>PRIVATE</script>'),2)
        self.key=self.r.incident(dict(endpoints=['10.23.45.67','Secret.Example.','secret.example','AA:BB:CC:DD:EE:FF']),3)
        self.r.finish(self.key,33,self.r.epoch,33)
    def tearDown(self):self.r.close();self.tmp.cleanup()
    def request(self,name='request',seconds=30):return self.r.request_export(name,self.key,seconds,self.r.epoch)
    def test_dedup_and_conflict(self):
        a=self.request(seconds=1);b=self.request(seconds=1.0);self.assertEqual(a,b)
        with self.assertRaisesRegex(Refused,'request_conflict'):self.request(seconds=2)
        self.assertEqual(self.r.db.execute('SELECT count(*) FROM holds').fetchone()[0],1)
        with self.assertRaisesRegex(Refused,'export_busy'):self.request('other')
    def test_cancel_releases_only_own_reference(self):
        self.request();self.r.cancel_export('request',self.r.epoch)
        self.assertEqual(self.r.db.execute('SELECT count(*) FROM holds').fetchone()[0],0)
        self.r.advance_exports();self.assertEqual(self.r.export_status('request')['state'],'CANCELLED')
    def test_unknown_reference_not_released(self):
        self.request()
        with self.r.db:self.r.db.execute('UPDATE holds SET token="different-owner"')
        with self.assertRaisesRegex(Refused,'reference_mismatch'):self.r.cancel_export('request',self.r.epoch)
        self.r.advance_exports();self.assertEqual(self.r.export_status('request')['state'],'BLOCKED')
        self.assertEqual(self.r.db.execute('SELECT token FROM holds').fetchone()[0],'different-owner')
    def test_ready_survives_gc_and_no_raw_values(self):
        self.request()
        with self.assertRaisesRegex(Refused,'reference_busy'):self.r.remove(self.key,self.r.epoch)
        self.r.advance_exports();self.r.advance_exports();out=self.r.read_snapshot('request');text=json.dumps(out)
        for value in ['SECRET','PRIVATE','secret.example','10.23.45.67','aabbccddeeff','0a172d43','<script>']:self.assertNotIn(value,text)
        self.assertEqual(out['snapshot']['incident']['endpoints'][1],out['snapshot']['incident']['endpoints'][2])
        groups={x['group']:x['state'] for x in out['snapshot']['observations'] if x['kind']=='state_object'}
        self.assertEqual(set(groups),{'links','addresses','routes'})
        self.assertEqual(groups['links']['interface'],groups['addresses']['interface'])
        self.assertEqual(groups['links']['interface'],groups['routes']['interface'])
        self.assertEqual(groups['addresses']['address'],groups['routes']['gateway'])
        self.assertEqual(groups['addresses']['address'],out['snapshot']['incident']['endpoints'][0])
        self.assertNotEqual(groups['routes']['destination'],groups['routes']['gateway'])
        self.assertEqual(groups['links']['mac'],out['snapshot']['incident']['endpoints'][3])
        self.r.remove(self.key,self.r.epoch);self.assertEqual(self.r.read_snapshot('request'),out)
    def test_restart_interrupts_and_stale_cancel_rejected(self):
        self.request();epoch=self.r.epoch;self.r.close();self.r=ExportRecorder(self.tmp.name)
        self.assertEqual(self.r.export_status('request')['state'],'INTERRUPTED')
        self.assertEqual(self.r.db.execute('SELECT count(*) FROM holds').fetchone()[0],0)
        with self.assertRaisesRegex(Refused,'stale_epoch'):self.r.cancel_export('request',epoch)
    def test_deadline_does_not_extend(self):
        from unittest.mock import patch
        self.request()
        deadline=self.r.export_status('request')['deadline']
        with patch('pathquill.exports.boottime',return_value=deadline+1):self.r.advance_exports()
        self.assertEqual(self.r.export_status('request')['state'],'EXPIRED')
        self.assertEqual(self.request()['deadline'],deadline)
    def test_cancel_snapshotting_and_ready(self):
        self.request();self.r.advance_exports();self.assertEqual(self.r.export_status('request')['state'],'SNAPSHOTTING')
        self.r.cancel_export('request',self.r.epoch);self.r.advance_exports()
        self.assertEqual(self.r.export_status('request')['state'],'CANCELLED')
        self.request('another');self.r.advance_exports();self.r.advance_exports()
        self.r.cancel_export('another',self.r.epoch)
        with self.assertRaisesRegex(Refused,'snapshot_not_ready'):self.r.read_snapshot('another')
    def test_manual_release_cannot_steal_export_hold(self):
        self.request();token=self.r.db.execute('SELECT token FROM holds').fetchone()[0]
        with self.assertRaisesRegex(Refused,'export_reference'):self.r.release(self.key,token,self.r.epoch)
        self.assertEqual(self.r.db.execute('SELECT token FROM holds').fetchone()[0],token)
    def test_history_is_finite_without_replay(self):
        for i in range(32):
            self.request('job_'+str(i));self.r.cancel_export('job_'+str(i),self.r.epoch)
        with self.assertRaisesRegex(Refused,'export_history_full'):self.request('extra')
        self.assertEqual(self.request('job_0')['state'],'CANCELLED')
    def test_ipv6_and_mac_canonical_aliases(self):
        from pathquill.redaction import Redactor
        r=Redactor()
        self.assertEqual(r.endpoint('2001:0DB8::1'),r.endpoint('2001:db8:0:0:0:0:0:1'))
        self.assertEqual(r.endpoint('AA-BB-CC-DD-EE-FF'),r.endpoint('aa:bb:cc:dd:ee:ff'))
        self.assertEqual(r.endpoint('Private.Example.'),r.endpoint('private.example'))

    def test_admission_abort_rolls_back_reference(self):
        import sqlite3
        self.r.db.execute("CREATE TRIGGER fail_job BEFORE INSERT ON exports BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.request()
        self.assertEqual(self.r.db.execute('SELECT count(*) FROM holds').fetchone()[0],0)
        self.assertEqual(self.r.db.execute('SELECT count(*) FROM exports').fetchone()[0],0)
    def test_snapshot_commit_abort_preserves_reference(self):
        import sqlite3
        self.request();self.r.advance_exports()
        self.r.db.execute("CREATE TRIGGER fail_snapshot BEFORE UPDATE OF snapshot ON exports BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.r.advance_exports()
        self.assertEqual(self.r.export_status('request')['state'],'SNAPSHOTTING')
        self.assertEqual(self.r.db.execute('SELECT count(*) FROM holds').fetchone()[0],1)
        self.r.db.execute('DROP TRIGGER fail_snapshot');self.r.db.commit();self.r.close();self.r=ExportRecorder(self.tmp.name)
        self.assertEqual(self.r.export_status('request')['state'],'INTERRUPTED')
    def test_render_cannot_extend_deadline(self):
        from unittest.mock import patch
        self.request();self.r.advance_exports();deadline=self.r.export_status('request')['deadline']
        with patch('pathquill.exports.boottime',side_effect=[deadline-1,deadline+1]):self.r.advance_exports()
        self.assertEqual(self.r.export_status('request')['state'],'EXPIRED')
        self.assertEqual(self.r.db.execute('SELECT snapshot FROM exports').fetchone()[0],None)
        self.assertEqual(self.r.db.execute('SELECT count(*) FROM holds').fetchone()[0],0)
    def test_restart_never_releases_unknown_owner(self):
        self.request()
        with self.r.db:self.r.db.execute('UPDATE holds SET token="new-owner"')
        self.r.close();self.r=ExportRecorder(self.tmp.name)
        self.assertEqual(self.r.export_status('request')['state'],'BLOCKED')
        self.assertEqual(self.r.db.execute('SELECT token FROM holds').fetchone()[0],'new-owner')
        with self.assertRaisesRegex(Refused,'export_busy'):self.request('another')
    def test_oversized_snapshot_fails_without_releasing_source_data(self):
        from unittest.mock import patch
        self.request();self.r.advance_exports()
        with patch('pathquill.exports.Redactor.snapshot',return_value='x'*262145):self.r.advance_exports()
        self.assertEqual(self.r.export_status('request')['state'],'FAILED')
        self.assertEqual(self.r.db.execute('SELECT count(*) FROM holds').fetchone()[0],0)
        self.assertEqual(self.r.db.execute('SELECT count(*) FROM incidents WHERE id=?',(self.key,)).fetchone()[0],1)

    def test_huge_integer_deadline_is_refused_without_mutation(self):
        with self.assertRaisesRegex(Refused,'deadline'):self.request(seconds=10**400)
        self.assertEqual(self.r.db.execute('SELECT count(*) FROM exports').fetchone()[0],0)
        self.assertEqual(self.r.db.execute('SELECT count(*) FROM holds').fetchone()[0],0)
