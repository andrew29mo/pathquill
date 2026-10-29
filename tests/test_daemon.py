import tempfile
import unittest
from unittest.mock import patch
from pathquill.recorder import Recorder
from pathquill.daemon import accept_result
class ResultTests(unittest.TestCase):
    def test_stale_has_no_writer_or_health_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=Recorder(tmp);health={'0':'success'};before=r.db.total_changes
            self.assertFalse(accept_result(r,health,{'host':'127.0.0.1'},0,'refused',0,1,1,2))
            self.assertEqual(health,{'0':'success'});self.assertEqual(r.db.total_changes,before);r.close()
    def test_commit_crosses_deadline_without_expired_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            r=Recorder(tmp);key=r.incident({},0)
            with patch('pathquill.daemon.boottime',return_value=31):
                self.assertTrue(accept_result(r,{},dict(host='127.0.0.1'),0,'refused',29,29.9,1,1))
            self.assertEqual(r.db.execute('SELECT end FROM incidents').fetchone()[0],30)
            r.finish(key,31,r.epoch,r.watermark)
            self.assertEqual(r.db.execute('SELECT state FROM incidents').fetchone()[0],'SEALED');r.close()

    def test_preincident_success_is_not_recovery(self):
        from pathquill.daemon import recovery_ready
        health={'0':'success','1':'success'}
        self.assertFalse(recovery_ready(health,{'0':0,'1':2},2,'RECORDING',1))
        self.assertTrue(recovery_ready(health,{'0':2,'1':2},2,'RECORDING',1))
        self.assertFalse(recovery_ready(health,{'0':2,'1':2},2,'DEGRADED',1))
