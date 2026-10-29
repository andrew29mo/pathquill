import errno
import tempfile
import unittest
from unittest.mock import patch
from pathquill.publication import PublicationRecorder,rename_new,package_bodies
from pathquill.core import Refused

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.r=PublicationRecorder(self.tmp.name)
        self.key=self.r.incident({},0);self.r.finish(self.key,30,self.r.epoch,30)
        self.r.request_export('work',self.key,60,self.r.epoch);self.r.advance_exports();self.r.advance_exports()
    def tearDown(self):self.r.close();self.tmp.cleanup()
    def crash_stage(self):
        with patch('pathquill.publication.rename_new',side_effect=SystemExit):
            with self.assertRaises(SystemExit):self.r.publish_export('work',self.r.epoch)
        return self.r.root/'packages'/('.stage-'+self.r.publication_status('work')['package'])
    def reopen(self):self.r.close();self.r=PublicationRecorder(self.tmp.name)
    def drain(self):
        for _ in range(5):self.r.advance_publications()
        self.assertEqual(self.r.publication_status('work')['state'],'CLEANED')
        self.assertEqual(self.r.publication_status('work')['bytes'],0)
    def test_complete_final_adopted_without_rewrite(self):
        def crash(a,b):rename_new(a,b);raise SystemExit
        with patch('pathquill.publication.rename_new',side_effect=crash):
            with self.assertRaises(SystemExit):self.r.publish_export('work',self.r.epoch)
        final=self.r.root/'packages'/self.r.publication_status('work')['package']
        before={p.name:(p.read_bytes(),p.stat().st_ino,p.stat().st_mtime_ns) for p in final.iterdir()}
        self.reopen();self.assertEqual(self.r.publication_status('work')['state'],'PUBLISHED')
        self.assertEqual(before,{p.name:(p.read_bytes(),p.stat().st_ino,p.stat().st_mtime_ns) for p in final.iterdir()})
    def test_partial_stage_cleanup_reserves_until_complete_and_restarts(self):
        stage=self.crash_stage();old=self.r.epoch;reserved=self.r.publication_status('work')['bytes']
        self.reopen();self.assertEqual(self.r.publication_status('work')['state'],'CLEANUP_PENDING')
        self.r.advance_publications();self.assertEqual(len(list(stage.iterdir())),2)
        self.assertEqual(self.r.publication_status('work')['bytes'],reserved)
        self.r.request_export('other',self.key,60,self.r.epoch)
        self.r.advance_exports();self.r.advance_exports()
        with self.assertRaisesRegex(Refused,'publication_requires_reconciliation'):self.r.publish_export('other',self.r.epoch)
        self.reopen()
        with self.assertRaisesRegex(Refused,'stale_epoch'):self.r.cancel_export('work',old)
        self.drain();self.assertFalse(stage.exists());self.assertEqual(self.r.export_status('work')['state'],'INTERRUPTED')
        with self.assertRaises(Refused):self.r.publish_export('work',self.r.epoch)
    def test_whole_first_file_before_fsync_is_recoverable(self):
        with patch('pathquill.publication.os.fsync',side_effect=SystemExit):
            with self.assertRaises(SystemExit):self.r.publish_export('work',self.r.epoch)
        self.reopen();self.drain()
    def test_unknown_file_preserved(self):
        stage=self.crash_stage();(stage/'unknown').write_text('keep')
        self.reopen();self.assertEqual(self.r.publication_status('work')['state'],'BLOCKED')
        for _ in range(5):self.r.advance_publications()
        self.assertEqual((stage/'unknown').read_text(),'keep');self.assertEqual(len(list(stage.iterdir())),4)
    def test_changed_known_file_preserved(self):
        stage=self.crash_stage();(stage/'snapshot.json').write_text('unexpected')
        self.reopen();self.assertEqual(self.r.publication_status('work')['state'],'BLOCKED')
        self.assertEqual((stage/'snapshot.json').read_text(),'unexpected')
    def test_cancel_pending_cleanup_is_durable(self):
        self.crash_stage();self.r.cancel_export('work',self.r.epoch);self.reopen();self.drain()
        self.assertEqual(self.r.export_status('work')['state'],'CANCELLED')
    def test_cleanup_sync_error_retains_reservation_and_recovers(self):
        stage=self.crash_stage();self.reopen();reserved=self.r.publication_status('work')['bytes']
        with patch('pathquill.publication.sync_dir',side_effect=OSError(errno.EIO,'fault')):self.r.advance_publications()
        self.assertEqual(self.r.publication_status('work')['state'],'BLOCKED')
        self.assertEqual(self.r.publication_status('work')['bytes'],reserved)
        self.reopen();self.drain();self.assertFalse(stage.exists())
    def test_missing_published_artifact_is_not_success(self):
        self.r.publish_export('work',self.r.epoch)
        final=self.r.root/'packages'/self.r.publication_status('work')['package'];(final/'index.html').unlink()
        self.reopen();self.assertEqual(self.r.publication_status('work')['state'],'BLOCKED')
        self.assertTrue((final/'snapshot.json').exists())
        for path in final.iterdir():path.unlink()
        final.rmdir();self.reopen()
        self.assertEqual(self.r.publication_status('work')['state'],'BLOCKED')
        self.assertGreater(self.r.publication_status('work')['bytes'],0)
    def test_no_owned_inode_never_deletes_stage(self):
        stage=self.crash_stage()
        with self.r.db:self.r.db.execute('UPDATE publications SET stage_ino=NULL,stage_dev=NULL')
        self.reopen();self.assertEqual(self.r.publication_status('work')['state'],'BLOCKED')
        self.assertEqual(len(list(stage.iterdir())),3)
    def test_cleanup_database_failure_keeps_credit_until_repaired(self):
        import sqlite3
        stage=self.crash_stage();self.reopen();reserved=self.r.publication_status('work')['bytes']
        with self.r.db:self.r.db.execute("CREATE TRIGGER deny_clean BEFORE UPDATE ON publications WHEN NEW.state='CLEANED' BEGIN SELECT RAISE(ABORT,'full'); END")
        for _ in range(3):self.r.advance_publications()
        with self.assertRaises(sqlite3.Error):self.r.advance_publications()
        self.assertFalse(stage.exists());self.assertEqual(self.r.publication_status('work')['bytes'],reserved)
        self.assertTrue(self.r.read_snapshot('work'))
        with self.r.db:self.r.db.execute('DROP TRIGGER deny_clean')
        self.reopen();self.drain()
    def test_file_replaced_during_cleanup_is_preserved(self):
        stage=self.crash_stage();self.reopen();self.r.advance_publications()
        target=next(stage.iterdir());data=target.read_bytes();replacement=stage/'replacement';replacement.write_bytes(data);replacement.chmod(0o600);replacement.replace(target)
        self.reopen();self.assertEqual(self.r.publication_status('work')['state'],'BLOCKED')
        self.r.advance_publications();self.assertEqual(target.read_bytes(),data)
    def test_damaged_published_retry_never_reports_success(self):
        self.r.publish_export('work',self.r.epoch)
        final=self.r.root/'packages'/self.r.publication_status('work')['package'];(final/'index.html').unlink()
        with self.assertRaisesRegex(Refused,'reconciliation'):self.r.publish_export('work',self.r.epoch)
        self.assertEqual(self.r.publication_status('work')['state'],'BLOCKED')

    def short_write_recovery(self,empty=False):
        import os
        original=os.fdopen
        expected=package_bodies(self.r.db.execute("SELECT snapshot FROM exports WHERE request='work'").fetchone()[0])['snapshot.json']
        count=0 if empty else len(expected)//2
        class InterruptedWriter:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):return self
            def __exit__(self,*args):self.stream.close()
            def write(self,data):
                self.stream.write(data[:count]);self.stream.flush()
                raise SystemExit('injected short write')
        def partial_open(fd,*args,**kwargs):return InterruptedWriter(original(fd,*args,**kwargs))
        with patch('pathquill.publication.os.fdopen',side_effect=partial_open):
            with self.assertRaises(SystemExit):self.r.publish_export('work',self.r.epoch)
        status=self.r.publication_status('work');stage=self.r.root/'packages'/('.stage-'+status['package'])
        self.assertEqual({p.name for p in stage.iterdir()},{'snapshot.json'})
        actual=(stage/'snapshot.json').read_bytes()
        self.assertEqual(actual,expected[:count]);self.assertLess(len(actual),len(expected))
        if not empty:self.assertGreater(len(actual),0)
        reserved=status['bytes'];self.reopen()
        self.assertEqual(self.r.publication_status('work')['state'],'CLEANUP_PENDING')
        self.assertEqual(self.r.publication_status('work')['bytes'],reserved)
        self.r.advance_publications();self.assertFalse((stage/'snapshot.json').exists())
        self.assertEqual(self.r.publication_status('work')['bytes'],reserved)
        self.reopen();self.drain();self.assertFalse(stage.exists())
    def test_strict_short_prefix_write_is_recoverable(self):self.short_write_recovery()
    def test_empty_short_write_is_recoverable(self):self.short_write_recovery(empty=True)
