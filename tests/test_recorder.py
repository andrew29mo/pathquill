import json
import tempfile
import unittest
from pathquill.recorder import Recorder
from pathquill.core import Refused
class RecorderTests(unittest.TestCase):
    def test_persistent_prebuffer(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Recorder(tmp)
            s.observe({'kind':'before'},100);key=s.incident({},110);s.observe({'kind':'after'},111)
            self.assertEqual(s.db.execute('SELECT count(*) FROM capture WHERE id=?',(key,)).fetchone()[0],2)
            s.close();s=Recorder(tmp)
            self.assertEqual(s.db.execute('SELECT count(*) FROM capture').fetchone()[0],2)
            self.assertEqual(s.db.execute('SELECT reason FROM incidents').fetchone()[0],'restart');s.close()
    def test_33rd_and_reclaim(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Recorder(tmp)
            for i in range(32):
                k=s.incident({},i*40);s.finish(k,i*40+30,s.epoch,i*40+30)
            with self.assertRaises(Refused):s.incident({},2000)
            self.assertEqual(s.db.execute('SELECT count(*) FROM incidents').fetchone()[0],32)
            s.reclaim(k);s.incident({},2000);s.close()
    def test_atomic_capture_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Recorder(tmp,byte_limit=150)
            s.observe({'kind':'x'*40},1);s.incident({},2)
            with self.assertRaises(Refused):s.observe({'kind':'x'*40},3)
            s.close()
    def test_ring_rotation_never_reuses_capture_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Recorder(tmp);s.observe({'kind':'first'},0);k=s.incident({},1)
            s.incident({},70);s.observe({'kind':'late'},70)
            self.assertEqual(s.db.execute('SELECT count(*) FROM capture WHERE id=?',(k,)).fetchone()[0],2)
            self.assertEqual(s.db.execute('SELECT seq FROM observations').fetchone()[0],2);s.close()
