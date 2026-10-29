import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from pathquill.core import Store,Inbox,Observer,Refused

class CoreTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.s=Store(self.tmp.name)
    def tearDown(self):self.s.close();self.tmp.cleanup()
    def test_gap_sticky(self):
        q=Inbox(count=1);self.assertTrue(q.put({'x':1}));self.assertFalse(q.put({'x':2}));self.assertEqual(q.drain()[1],1)
        o=Observer();o.lost('ENOBUFS');o.synchronized(True);self.assertIsNone(o.gaps[0]['lost_count'])
    def test_old_probe_and_families(self):
        o=Observer();g=o.generation;o.result('x',6,g,False);o.result('x',4,g,True);self.assertFalse(o.health[('x',6)])
        o.lost('restart')
        with self.assertRaises(Refused):o.result('x',6,g,True)
    def test_window_cap_and_barrier(self):
        k=self.s.trigger(100,{});self.s.trigger(210,{})
        self.assertEqual(self.s.db.execute('SELECT end FROM incidents').fetchone()[0],220)
        with self.assertRaises(Refused):self.s.finish(k,220,self.s.epoch,219)
        self.s.finish(k,220,self.s.epoch,220);self.assertFalse(json.loads(self.s.export(k)['json'])['recovered'])
    def test_capacity_preserves(self):
        self.s.slots=1;k=self.s.trigger(0,{});self.s.finish(k,30,self.s.epoch,30)
        with self.assertRaises(Refused):self.s.trigger(40,{})
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM incidents').fetchone()[0],1)
        self.s.delete(k);self.s.trigger(40,{})
    def test_restart_and_lock(self):
        k=self.s.trigger(0,{});old=self.s.epoch
        with self.assertRaises(Refused):Store(self.tmp.name)
        self.s.close();self.s=Store(self.tmp.name)
        self.assertEqual(self.s.db.execute('SELECT coverage,reason FROM incidents').fetchone(),('PARTIAL','restart'))
        with self.assertRaises(Refused):self.s.finish(k,40,old,40)
    def test_redaction(self):
        k=self.s.trigger(0,dict(endpoints=['2001:0db8::1','2001:db8::1','SECRET.EXAMPLE.','secret.example'],extra='<script>private</script>'))
        self.s.finish(k,30,self.s.epoch,30);v=self.s.export(k)
        self.assertNotIn('private',v['html']);self.assertNotIn('secret',v['json']);self.assertNotIn('2001',v['json'])
        a=json.loads(v['json'])['endpoints'];self.assertEqual(a[0],a[1]);self.assertEqual(a[2],a[3])
    def test_sqlite_full(self):
        self.s.db.execute('PRAGMA max_page_count='+str(self.s.db.execute('PRAGMA page_count').fetchone()[0]))
        failed=False
        for i in range(32):
            try:
                k=self.s.trigger(i*40,dict(endpoints=['x'*3500]));self.s.finish(k,i*40+30,self.s.epoch,i*40+30)
            except sqlite3.OperationalError:failed=True;break
        self.assertTrue(failed);self.assertTrue(self.s.degraded)
        with self.assertRaises(Refused):self.s.trigger(2000,{})
