import errno
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
from pathquill.publication import PublicationRecorder,rename_new
from pathquill.core import Refused

class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.r=PublicationRecorder(self.tmp.name)
        self.key=self.r.incident(dict(endpoints=['10.23.45.67','PRIVATE.example']),0)
        self.r.finish(self.key,30,self.r.epoch,30)
        self.r.request_export('secret_request',self.key,60,self.r.epoch)
        self.r.advance_exports();self.r.advance_exports()
    def tearDown(self):self.r.close();self.tmp.cleanup()
    def publish(self):return self.r.publish_export('secret_request',self.r.epoch)
    def test_complete_package_dedup_cancel_boundary(self):
        result=self.publish();self.assertEqual(result['state'],'PUBLISHED')
        directory=self.r.root/'packages'/result['package'];self.assertEqual({p.name for p in directory.iterdir()},{'snapshot.json','index.html','manifest.json'})
        fixed=self.r.read_snapshot('secret_request')
        self.assertEqual(json.loads((directory/'snapshot.json').read_text()),fixed['snapshot'])
        self.assertEqual((directory/'index.html').read_text(),fixed['preview_html'])
        self.assertEqual(hashlib.sha256((directory/'snapshot.json').read_bytes()).hexdigest(),fixed['digest'])
        manifest=json.loads((directory/'manifest.json').read_text())
        self.assertEqual(manifest['schema'],'pathquill-package-v1')
        self.assertEqual(set(manifest['files']),{'snapshot.json','index.html'})
        for name,entry in manifest['files'].items():
            data=(directory/name).read_bytes();self.assertEqual(len(data),entry['bytes']);self.assertEqual(hashlib.sha256(data).hexdigest(),entry['sha256'])
        for p in directory.iterdir():
            for raw in ('10.23.45.67','PRIVATE','secret_request',self.key):self.assertNotIn(raw,p.read_text())
        self.assertEqual(self.publish(),result)
        with self.assertRaisesRegex(Refused,'already_published'):self.r.cancel_export('secret_request',self.r.epoch)
    def test_cancel_before_publish(self):
        self.r.cancel_export('secret_request',self.r.epoch)
        with self.assertRaisesRegex(Refused,'snapshot_not_ready'):self.publish()
        self.assertFalse((self.r.root/'packages').exists())
    def test_noreplace_even_empty_directory(self):
        directory=self.r.package_directory();a=directory/'a';b=directory/'b';a.mkdir();b.mkdir();(a/'marker').write_text('keep')
        with self.assertRaises(OSError):rename_new(a,b)
        self.assertEqual((a/'marker').read_text(),'keep');self.assertEqual(list(b.iterdir()),[])
    def test_write_failure_blocks_without_success_and_keeps_snapshot(self):
        with patch('pathquill.publication.sync_dir',side_effect=OSError(errno.ENOSPC,'full')):
            with self.assertRaisesRegex(Refused,'publication_incomplete'):self.publish()
        self.assertEqual(self.r.publication_status('secret_request')['state'],'BLOCKED')
        self.assertTrue(self.r.read_snapshot('secret_request'))
        with self.assertRaisesRegex(Refused,'reconciliation'):self.publish()
    def test_deadline_and_stale_epoch_refuse_before_files(self):
        with self.assertRaisesRegex(Refused,'stale_epoch'):self.r.publish_export('secret_request','old')
        with self.r.db:self.r.db.execute('UPDATE exports SET deadline=0')
        with self.assertRaisesRegex(Refused,'deadline'):self.publish()
        self.assertFalse((self.r.root/'packages').exists())
    def test_budget_refusal_does_not_delete_existing_files(self):
        directory=self.r.package_directory();other=directory/'other';other.mkdir();(other/'keep').write_bytes(b'x'*4194304)
        with self.assertRaisesRegex(Refused,'package_byte_budget'):self.publish()
        self.assertEqual((other/'keep').stat().st_size,4194304)
        self.assertIsNone(self.r.db.execute('SELECT 1 FROM publications').fetchone())
    def test_symlink_directory_refused(self):
        (self.r.root/'packages').symlink_to(self.r.root,target_is_directory=True)
        with self.assertRaisesRegex(Refused,'private_package_directory'):self.publish()
    def test_restart_blocks_uncertain_intent_and_rejects_old_epoch(self):
        old=self.r.epoch
        with self.r.db:self.r.db.execute("INSERT INTO publications VALUES('secret_request','opaque','PREPARING',100,'digest')")
        self.r.close();self.r=PublicationRecorder(self.tmp.name)
        self.assertEqual(self.r.publication_status('secret_request')['state'],'BLOCKED')
        with self.assertRaisesRegex(Refused,'stale_epoch'):self.r.publish_export('secret_request',old)
        with self.assertRaisesRegex(Refused,'reconciliation'):self.publish()
    def test_atomic_boundary_has_all_files_before_final_name(self):
        real=rename_new
        def inspect(source,destination):
            self.assertFalse(destination.exists())
            self.assertEqual({p.name for p in source.iterdir()},{'snapshot.json','index.html','manifest.json'})
            real(source,destination)
        with patch('pathquill.publication.rename_new',side_effect=inspect):self.publish()
    def test_failure_after_rename_is_ambiguous_not_success(self):
        from pathquill.publication import sync_dir
        calls=[]
        def sync(path):
            calls.append(path)
            if len(calls)==2:raise OSError(errno.EIO,'sync failed')
            sync_dir(path)
        with patch('pathquill.publication.sync_dir',side_effect=sync):
            with self.assertRaisesRegex(Refused,'publication_incomplete'):self.publish()
        status=self.r.publication_status('secret_request');self.assertEqual(status['state'],'BLOCKED')
        self.assertTrue((self.r.root/'packages'/status['package']/'manifest.json').exists())
        with self.assertRaisesRegex(Refused,'reconciliation'):self.r.cancel_export('secret_request',self.r.epoch)
    def test_published_survives_restart_unchanged(self):
        result=self.publish();old=self.r.epoch;self.r.close();self.r=PublicationRecorder(self.tmp.name)
        self.assertEqual(self.publish(),result)
        with self.assertRaisesRegex(Refused,'stale_epoch'):self.r.publish_export('secret_request',old)
    def test_entry_budget_does_not_remove_foreign_directory(self):
        directory=self.r.package_directory()
        for i in range(32):(directory/str(i)).mkdir()
        with self.assertRaisesRegex(Refused,'package_entry_budget'):self.publish()
        self.assertEqual(len(list(directory.iterdir())),32)
    def test_sqlite_failure_after_rename_never_returns_success(self):
        import sqlite3
        with self.r.db:self.r.db.execute("CREATE TRIGGER fail_publish BEFORE UPDATE ON publications WHEN NEW.state='PUBLISHED' BEGIN SELECT RAISE(ABORT,'commit denied'); END")
        with self.assertRaises(sqlite3.Error):self.publish()
        self.assertTrue(self.r.degraded)
        self.assertEqual(self.r.publication_status('secret_request')['state'],'PREPARING')
        package=self.r.publication_status('secret_request')['package']
        self.assertTrue((self.r.root/'packages'/package/'snapshot.json').exists())
        self.r.close();self.r=PublicationRecorder(self.tmp.name)
        self.assertEqual(self.r.publication_status('secret_request')['state'],'BLOCKED')

    def test_expiry_after_staging_does_not_publish(self):
        with patch('pathquill.publication.boottime',side_effect=[0,float('inf')]):
            with self.assertRaisesRegex(Refused,'publication_incomplete'):self.publish()
        status=self.r.publication_status('secret_request')
        self.assertEqual(status['state'],'BLOCKED')
        directory=self.r.root/'packages'
        self.assertFalse((directory/status['package']).exists())
        self.assertEqual({p.name for p in (directory/('.stage-'+status['package'])).iterdir()},{'snapshot.json','index.html','manifest.json'})
        self.assertTrue(self.r.read_snapshot('secret_request'))
    def test_publication_collision_preserves_existing_result(self):
        from types import SimpleNamespace
        directory=self.r.package_directory();existing=directory/('a'*32);existing.mkdir()
        (existing/'marker').write_text('keep')
        with patch('pathquill.publication.uuid.uuid4',return_value=SimpleNamespace(hex='a'*32)):
            with self.assertRaisesRegex(Refused,'publication_incomplete'):self.publish()
        self.assertEqual((existing/'marker').read_text(),'keep')
        self.assertEqual(self.r.publication_status('secret_request')['state'],'BLOCKED')

    def test_package_directory_creation_error_is_structured_and_retryable(self):
        deadline=self.r.export_status('secret_request')['deadline']
        with patch('pathquill.publication.os.mkdir',side_effect=OSError(errno.ENOSPC,'private path must not escape')):
            with self.assertRaisesRegex(Refused,'^publication_unavailable$'):self.publish()
        self.assertIsNone(self.r.db.execute('SELECT 1 FROM publications').fetchone())
        self.assertTrue(self.r.read_snapshot('secret_request'))
        self.assertEqual(self.publish()['state'],'PUBLISHED')
        self.assertEqual(self.r.export_status('secret_request')['deadline'],deadline)
