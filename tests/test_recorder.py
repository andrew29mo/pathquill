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
            s.incident({},25);s.incident({},50);s.observe({'kind':'late'},70)
            self.assertEqual(s.db.execute('SELECT count(*) FROM capture WHERE id=?',(k,)).fetchone()[0],2)
            self.assertEqual(s.db.execute('SELECT seq FROM observations').fetchone()[0],2);s.close()

    def test_expired_capture_rejects_late_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Recorder(tmp);k=s.incident({},0);s.observe({'late':True},200)
            with self.assertRaisesRegex(Refused,'window_expired'):s.incident({},200)
            self.assertEqual(s.db.execute('SELECT count(*) FROM capture').fetchone()[0],0);s.close()
    def test_metadata_budget_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Recorder(tmp,byte_limit=1)
            with self.assertRaises(Refused):s.incident({'x':'y'*100},0)
            self.assertEqual(s.db.execute('SELECT count(*) FROM incidents').fetchone()[0],0);s.close()
        with tempfile.TemporaryDirectory() as tmp:
            s=Recorder(tmp);s.observe({'x':1},0);k=s.incident({},1);s.finish(k,31,s.epoch,31);s.delete(k)
            self.assertEqual(s.db.execute('SELECT count(*) FROM capture').fetchone()[0],0);s.close()
    def test_same_boot_prebuffer_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Recorder(tmp);s.observe({'before':True},1);s.close();s=Recorder(tmp);k=s.incident({},2)
            self.assertEqual(s.db.execute('SELECT count(*) FROM capture WHERE id=?',(k,)).fetchone()[0],1);s.close()
    def test_public_directory_rejected(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'public';p.mkdir(mode=0o755)
            with self.assertRaisesRegex(Refused,'private_owned'):Recorder(p)
    def test_numeric_endpoint_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Recorder(tmp)
            with self.assertRaises(ValueError):s.probe('localhost',80)
            s.close()
    def test_truncated_dns_answer_is_unknown(self):
        import socket,threading
        with tempfile.TemporaryDirectory() as tmp:
            s=Recorder(tmp);udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);udp.settimeout(2);udp.bind(('127.0.0.1',0))
            def reply():
                try:
                    data,peer=udp.recvfrom(4096)
                    # Claims one answer but sends no answer RR.
                    udp.sendto(data[:2]+b'\x81\x80'+data[4:6]+b'\x00\x01'+data[8:],peer)
                finally:udp.close()
            t=threading.Thread(target=reply);port=udp.getsockname()[1];t.start()
            try:
                self.assertEqual(s.dns('127.0.0.1',port),'unknown')
                self.assertEqual(s.db.execute('SELECT count(*) FROM incidents').fetchone()[0],0)
            finally:t.join(3);s.close()
