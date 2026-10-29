import copy
import unittest
from tools.closeout_checks import resource_check,cleanup_safe

class CloseoutChecks(unittest.TestCase):
    def samples(self):
        return [dict(seconds=i*2,pid=17,invocation='same',epoch='same',restarts=0,
                     rss_kib=20000,fds=8,threads=2,allocated_store_bytes=1048576) for i in range(151)]
    def test_fixed_resource_acceptance_and_negative_controls(self):
        original=self.samples();self.assertEqual(resource_check(original)['rss_window_growth_kib'],0)
        for field,value in [('rss_kib',24000),('fds',15),('threads',3),('pid',18),('epoch','new'),('invocation','new'),('restarts',1),('allocated_store_bytes',25*1024*1024)]:
            samples=copy.deepcopy(original)
            for s in samples[-30:]:s[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):resource_check(samples)
        with self.assertRaises(ValueError):resource_check(original[:-1])
        with self.assertRaises(ValueError):resource_check(original[:60]+original[70:])
        with self.assertRaises(ValueError):resource_check(original[30:])
        with self.assertRaises(ValueError):resource_check(original[:60]+original[59:])
    def test_cleanup_requires_success_and_empty_cgroup(self):
        self.assertTrue(cleanup_safe(0,'0','inactive',''))
        for args in [(1,'0','inactive',''),(0,'0','inactive','42\n'),(0,'7','inactive',''),(0,'0','activating','')]:
            with self.subTest(args=args):self.assertFalse(cleanup_safe(*args))
    def test_snapshot_requires_actual_trigger_then_recovery(self):
        from tools.closeout_checks import snapshot_evidence
        s=dict(schema='pathquill-snapshot-v1',incident=dict(state='SEALED',recovered=True,window_seconds=30),observations=[dict(order=1,kind='tcp',outcome='refused',relative_seconds=-.01),dict(order=2,kind='tcp',outcome='success',relative_seconds=1)])
        self.assertEqual(snapshot_evidence(s)['outcomes'],dict(refused=1,success=1))
        for rows in [[],[dict(order=1,kind='progress',relative_seconds=1)],[s['observations'][0]],[dict(order=1,kind='tcp',outcome='success',relative_seconds=1),dict(order=2,kind='tcp',outcome='refused',relative_seconds=-.01)],[dict(order=1,kind='tcp',outcome='refused',relative_seconds=-30),s['observations'][1]]]:
            bad=copy.deepcopy(s);bad['observations']=rows
            with self.subTest(rows=rows),self.assertRaises(ValueError):snapshot_evidence(bad)
