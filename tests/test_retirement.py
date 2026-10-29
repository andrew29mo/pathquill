import tempfile
import unittest
from unittest.mock import patch
from pathquill.publication import PublicationRecorder
from pathquill.core import Refused
from pathquill.archive import archive_store,new_store

class RetirementTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=__import__('pathlib').Path(self.tmp.name)/'store';self.r=PublicationRecorder(self.root)
        self.key=self.r.incident({},0);self.r.finish(self.key,30,self.r.epoch,30)
        self.r.request_export('work',self.key,60,self.r.epoch);self.r.advance_exports();self.r.advance_exports()
        self.result=self.r.publish_export('work',self.r.epoch);self.final=self.root/'packages'/self.result['package']
    def tearDown(self):
        if self.r:self.r.close()
        self.tmp.cleanup()
    def retire(self):return self.r.retire_publication('work',self.result['package'],self.r.epoch)
    def reopen(self):self.r.close();self.r=PublicationRecorder(self.root)
    def drain(self):
        for _ in range(5):self.r.advance_publications()
    def test_retire_reserves_credit_across_interrupted_delete(self):
        snapshot=self.r.read_snapshot('work');snapshot_bytes=self.r.usage()['snapshots']['bytes'];self.assertGreater(snapshot_bytes,0)
        self.assertEqual(self.retire()['state'],'RETIRE_PENDING');reserved=self.result['bytes'];self.r.advance_publications()
        self.assertEqual(self.r.publication_status('work')['bytes'],reserved);self.assertEqual(len(list(self.final.iterdir())),2)
        self.assertEqual(self.r.usage()['snapshots']['bytes'],snapshot_bytes);self.assertEqual(self.r.read_snapshot('work'),snapshot)
        with self.assertRaisesRegex(Refused,'retirement_in_progress'):self.r.cancel_export('work',self.r.epoch)
        self.reopen();self.drain();self.assertFalse(self.final.exists())
        self.assertEqual(self.r.publication_status('work')['bytes'],0);self.assertEqual(self.r.export_status('work')['state'],'RETIRED')
        self.assertEqual(self.r.usage()['snapshots']['bytes'],0);self.assertEqual(self.r.db.execute("SELECT snapshot,digest FROM exports WHERE request='work'").fetchone(),(None,None))
        self.assertEqual(self.retire()['state'],'CLEANED')
        self.assertEqual(self.r.usage()['export_history']['used'],1)
        with self.assertRaises(Refused):self.r.publish_export('work',self.r.epoch)
    def test_unknown_data_not_deleted(self):
        (self.final/'unknown').write_text('keep')
        with self.assertRaisesRegex(Refused,'publication_not_published'):self.retire()
        self.assertEqual((self.final/'unknown').read_text(),'keep');self.assertEqual(len(list(self.final.iterdir())),4)
    def test_replacement_after_retire_intent_blocks(self):
        self.retire();target=self.final/'snapshot.json';target.write_text('changed')
        self.r.advance_publications();self.assertEqual(self.r.publication_status('work')['state'],'BLOCKED');self.assertEqual(target.read_text(),'changed')
    def test_package_and_epoch_binding(self):
        with self.assertRaisesRegex(Refused,'package_mismatch'):self.r.retire_publication('work','other',self.r.epoch)
        with self.assertRaisesRegex(Refused,'stale_epoch'):self.r.retire_publication('work',self.result['package'],'old')
    def test_sqlite_failure_does_not_free_retirement_credit(self):
        import sqlite3
        snapshot=self.r.read_snapshot('work');snapshot_bytes=self.r.usage()['snapshots']['bytes']
        self.retire();reserved=self.result['bytes']
        with self.r.db:self.r.db.execute("CREATE TRIGGER deny_retire BEFORE UPDATE ON publications WHEN NEW.state='CLEANED' BEGIN SELECT RAISE(ABORT,'fault'); END")
        for _ in range(3):self.r.advance_publications()
        with self.assertRaises(sqlite3.Error):self.r.advance_publications()
        self.assertEqual(self.r.publication_status('work')['bytes'],reserved)
        self.assertEqual(self.r.usage()['snapshots']['bytes'],snapshot_bytes);self.assertEqual(self.r.read_snapshot('work'),snapshot)
        with self.r.db:self.r.db.execute('DROP TRIGGER deny_retire')
        self.reopen();self.drain();self.assertEqual(self.r.publication_status('work')['bytes'],0)
        self.assertEqual(self.r.usage()['snapshots']['bytes'],0);self.assertEqual(self.r.db.execute("SELECT snapshot,digest FROM exports WHERE request='work'").fetchone(),(None,None))
    def test_archive_and_fresh_store_preserve_old_history(self):
        self.retire();self.drain()
        for i in range(31):
            request='cancel_'+str(i);self.r.request_export(request,self.key,60,self.r.epoch);self.r.cancel_export(request,self.r.epoch)
        with self.assertRaisesRegex(Refused,'export_history_full'):self.r.request_export('overflow',self.key,60,self.r.epoch)
        identity=self.r.store_id;old_epoch=self.r.epoch
        self.r.seal_store(self.r.epoch);self.r.close();self.r=None
        with self.assertRaisesRegex(Refused,'store_sealed'):PublicationRecorder(self.root)
        receipt=archive_store(self.root,identity);self.assertEqual(receipt['history_used'],32);self.assertEqual(archive_store(self.root,identity),receipt)
        fresh=self.root.parent/'new';result=new_store(fresh,self.root,identity);self.assertNotEqual(result['store_id'],identity)
        r=PublicationRecorder(fresh)
        try:
            self.assertEqual(r.store_id,result['store_id'])
            self.assertEqual(r.usage()['export_history']['remaining'],32)
            with self.assertRaisesRegex(Refused,'stale_epoch'):r.request_export('work',self.key,60,old_epoch)
        finally:r.close()
        with self.assertRaisesRegex(Refused,'new_store_exists'):new_store(fresh,self.root,identity)
    def test_archive_refuses_live_store_and_unknown_entries(self):
        with self.assertRaisesRegex(Refused,'writer_busy'):archive_store(self.root,self.r.store_id)
        identity=self.r.store_id;self.r.seal_store(self.r.epoch);self.r.close();self.r=None
        (self.root/'unknown').write_text('keep')
        with self.assertRaisesRegex(Refused,'archive_unknown_entry'):archive_store(self.root,identity)
        self.assertEqual((self.root/'unknown').read_text(),'keep')
    def test_seal_refuses_pending_retirement(self):
        self.retire()
        with self.assertRaisesRegex(Refused,'publication_requires_reconciliation'):self.r.seal_store(self.r.epoch)
        self.assertFalse(self.r.sealed)
    def test_partial_archive_receipt_preserved_and_wrong_store_rejected(self):
        identity=self.r.store_id;self.r.seal_store(self.r.epoch);self.r.close();self.r=None
        pending=self.root/'.archive.pending';pending.write_bytes(b'unknown');pending.chmod(0o600)
        with self.assertRaisesRegex(Refused,'store_mismatch'):archive_store(self.root,'wrong')
        with self.assertRaisesRegex(Refused,'archive_incomplete'):archive_store(self.root,identity)
        self.assertEqual(pending.read_bytes(),b'unknown');self.assertFalse((self.root/'archive.json').exists())
    def test_archive_sync_failure_is_not_success_and_retry_resyncs(self):
        import errno
        identity=self.r.store_id;self.r.seal_store(self.r.epoch);self.r.close();self.r=None
        with patch('pathquill.archive.sync_file',side_effect=OSError(errno.EIO,'fault')):
            with self.assertRaises(OSError):archive_store(self.root,identity)
        self.assertTrue((self.root/'.archive.pending').exists());self.assertFalse((self.root/'archive.json').exists())
        self.assertEqual(archive_store(self.root,identity)['store_id'],identity)
        with patch('pathquill.archive.sync_file',side_effect=OSError(errno.EIO,'fault')):
            with self.assertRaises(OSError):archive_store(self.root,identity)

    def test_new_store_refuses_unreconciled_archive_pending(self):
        identity=self.r.store_id;self.r.seal_store(self.r.epoch);self.r.close();self.r=None
        archive_store(self.root,identity)
        pending=self.root/'.archive.pending';pending.write_bytes(b'unknown');pending.chmod(0o600)
        fresh=self.root.parent/'fresh'
        with self.assertRaisesRegex(Refused,'archive_requires_reconciliation'):new_store(fresh,self.root,identity)
        self.assertFalse(fresh.exists());self.assertEqual(pending.read_bytes(),b'unknown')
    def test_relative_archive_path_refused(self):
        import os
        identity=self.r.store_id;self.r.seal_store(self.r.epoch);self.r.close();self.r=None
        archive_store(self.root,identity);fresh=self.root.parent/'fresh'
        with self.assertRaisesRegex(Refused,'absolute_archive_path_required'):new_store(fresh,os.path.relpath(self.root),identity)
        self.assertFalse(fresh.exists())

    def test_complete_linked_pending_can_reconcile_before_handoff(self):
        import os
        identity=self.r.store_id;self.r.seal_store(self.r.epoch);self.r.close();self.r=None
        receipt=archive_store(self.root,identity)
        os.link(self.root/'archive.json',self.root/'.archive.pending')
        fresh=self.root.parent/'fresh'
        with self.assertRaisesRegex(Refused,'archive_requires_reconciliation'):new_store(fresh,self.root,identity)
        self.assertEqual(archive_store(self.root,identity),receipt)
        self.assertFalse((self.root/'.archive.pending').exists())
        self.assertNotEqual(new_store(fresh,self.root,identity)['store_id'],identity)
