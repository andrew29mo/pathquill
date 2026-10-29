import tempfile
import unittest
from pathquill.core import Refused,boottime
from pathquill.managed import ManagedRecorder
class ManagedTests(unittest.TestCase):
    def test_control_seals_when_data_full(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=ManagedRecorder(tmp,byte_limit=128);k=s.incident({},0)
            for i in range(4):s.observe({'body':'x'*100},i)
            s.observe({'kind':'progress'},31);self.assertGreater(s.usage()['loss'],0)
            self.assertTrue(s.finish(k,31,s.epoch,s.watermark))
            self.assertEqual(s.db.execute('SELECT state,coverage FROM incidents').fetchone(),('SEALED','PARTIAL'));s.close()
    def test_retention_and_hold(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=ManagedRecorder(tmp,retention=10);k=s.incident({},0);s.finish(k,30,s.epoch,30)
            anchor=s.db.execute('SELECT sealed FROM lifetime').fetchone()[0]
            self.assertEqual(s.collect(s.epoch,anchor+9),[])
            token=s.hold(k,s.epoch)
            self.assertEqual(s.collect(s.epoch,anchor+11),[])
            with self.assertRaisesRegex(Refused,'reference_busy'):s.remove(k,s.epoch)
            epoch=s.epoch;before=s.db.execute('SELECT boot,sealed,retention FROM lifetime').fetchone();s.close();s=ManagedRecorder(tmp)
            self.assertEqual(s.db.execute('SELECT boot,sealed,retention FROM lifetime').fetchone(),before)
            with self.assertRaisesRegex(Refused,'stale_epoch'):s.release(k,token,epoch)
            self.assertEqual(s.collect(s.epoch,anchor+11),[])
            s.release(k,token,s.epoch);self.assertEqual(s.collect(s.epoch,anchor+11),[k]);s.close()
    def test_active_never_collected(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=ManagedRecorder(tmp);k=s.incident({},0)
            self.assertEqual(s.collect(s.epoch,1e12),[])
            with self.assertRaisesRegex(Refused,'capture_busy'):s.remove(k,s.epoch)
            s.close()
    def test_new_boot_reanchors_without_early_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=ManagedRecorder(tmp,retention=10);k=s.incident({},0);s.finish(k,30,s.epoch,30)
            with s.db:s.db.execute('UPDATE lifetime SET boot="old-boot",sealed=0')
            s.close();begin=boottime();s=ManagedRecorder(tmp)
            anchor,retention=s.db.execute('SELECT sealed,retention FROM lifetime').fetchone()
            self.assertGreaterEqual(anchor,begin);self.assertEqual(retention,10)
            self.assertEqual(s.collect(s.epoch,anchor+9),[]);s.close()
    def test_delete_api_cannot_bypass_hold(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=ManagedRecorder(tmp);k=s.incident({},0);s.finish(k,30,s.epoch,30);s.hold(k,s.epoch)
            with self.assertRaisesRegex(Refused,'reference_busy'):s.delete(k)
            with self.assertRaisesRegex(Refused,'reference_busy'):s.reclaim(k)
            s.close()

    def test_deadline_float_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=ManagedRecorder(tmp);first=4092.0002469134;k=s.incident({},first)
            end=s.db.execute('SELECT end FROM incidents').fetchone()[0]
            self.assertEqual(end,first+30)
            self.assertLess(end-first,30)  # subtraction rounds across exponent boundary
            with self.assertRaisesRegex(Refused,'window_not_drained'):s.finish(k,end-0.000001,s.epoch,end)
            self.assertTrue(s.finish(k,end,s.epoch,end));s.close()
    def test_32_unexpired_incidents_reject_33_without_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=ManagedRecorder(tmp)
            for i in range(32):
                key=s.incident({},i*40);self.assertIsNotNone(key);s.finish(key,i*40+30,s.epoch,i*40+30)
            self.assertIsNone(s.incident({},2000))
            self.assertEqual(s.usage()['incidents'],32);self.assertEqual(s.usage()['refusals'],1)
            self.assertEqual(s.collect(s.epoch,boottime()+1),[]);s.close()

    def test_unknown_retention_migrates_conservatively(self):
        from pathquill.recorder import Recorder
        with tempfile.TemporaryDirectory() as tmp:
            old=Recorder(tmp);key=old.incident({},0);old.finish(key,30,old.epoch,30);old.close()
            s=ManagedRecorder(tmp,retention=1)
            anchor,duration=s.db.execute('SELECT sealed,retention FROM lifetime').fetchone()
            self.assertEqual(duration,86400);self.assertEqual(s.collect(s.epoch,anchor+2),[]);s.close()
