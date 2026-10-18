"""Recovery receipt/atomic-sync refusals. Crypto is exercised separately with age."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

from adc_core.operations_store import PrivateStore
from scripts.g4_course import digest, prune_backups, backup_inventory
from scripts.g4_remote import Remote
from scripts.recovery_receipts import ReceiptBook, artifact, file_digest, instant


class RecoveryReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
        self.project = 'adc_g4_111111111111'
        self.source = 'a' * 40
        self.image = 'sha256:' + 'b' * 64
        self.destination = self.root / 'mac'
        self.destination.mkdir(mode=0o700)
        self.key = self.private(self.root / 'identity', b'synthetic-current-key')
        self.book = ReceiptBook(self.destination / 'recovery', self.project)

    def private(self, path, data):
        path.write_bytes(data)
        os.chmod(path, 0o600)
        return path

    def point(self, *, hours=1, data=b'ciphertext', project=None, source=None):
        when = self.now - timedelta(hours=hours)
        project = project or self.project
        name = 'backup-' + when.strftime('%Y%m%dT%H%M%S%fZ') + '-' + project + '.tar.age'
        path = self.private(self.destination / name, data)
        row = dict(name=name, project=project, created_at=when.isoformat(), size=len(data), sha256=digest(path))
        meta = dict(project=project, source_commit=source or self.source, created_at=when.isoformat(),
                    images={'app': self.image}, recovery_point_basis='BACKUP_START_CONSERVATIVE')
        return artifact(meta, row)

    def status(self, **kwargs):
        return self.book.status(self.source, self.image, self.destination, mode='mac',
                                identity_file=self.key, now=self.now, **kwargs)

    def record(self, fact):
        self.book.record('created', fact, now=self.now)
        self.book.record('downloaded', fact, key_sha256=file_digest(self.key), now=self.now)

    def test_fresh_separate_facts_never_invent_independent_restore(self):
        self.record(self.point())
        status = self.status()
        self.assertEqual(status['conditions']['created']['state'], 'HEALTHY')
        self.assertEqual(status['conditions']['downloaded']['state'], 'HEALTHY')
        self.assertEqual(status['conditions']['restored']['state'], 'UNKNOWN')
        self.assertEqual(status['code'], 3)
        self.assertIsNone(self.book.load()['latest']['restored'])

    def test_redownload_does_not_refresh_old_recovery_point(self):
        fact = self.point(hours=28)
        self.record(fact)
        self.book.record('downloaded', fact, key_sha256=file_digest(self.key), now=self.now+timedelta(hours=1))
        status = self.book.status(self.source, self.image, self.destination, mode='mac', identity_file=self.key, now=self.now+timedelta(hours=1))
        self.assertEqual(status['conditions']['downloaded']['state'], 'WARNING')
        self.assertEqual(status['conditions']['downloaded']['age_seconds'], 29*3600)
        self.assertEqual(status['conditions']['downloaded']['recovery_point'], fact['created_at'])

    def test_older_upload_cannot_replace_a_newer_accepted_point(self):
        newer, older = self.point(hours=1), self.point(hours=5)
        self.record(newer)
        self.assertFalse(self.book.record('downloaded', older, key_sha256=file_digest(self.key), now=self.now))
        self.assertEqual(self.book.load()['latest']['downloaded']['artifact'], newer)

    def test_stale_server_observation_is_independent_from_mac_copy(self):
        self.record(self.point())
        result = self.book.status(self.source, self.image, self.destination, mode='mac', identity_file=self.key, now=self.now+timedelta(seconds=91))
        self.assertEqual(result['conditions']['created']['reason'], 'SERVER_OBSERVATION_STALE')
        self.assertEqual(result['conditions']['downloaded']['state'], 'HEALTHY')

    def test_new_key_corrupt_archive_and_absent_archive_do_not_establish_health(self):
        fact = self.point()
        self.record(fact)
        self.private(self.key, b'replaced-key')
        self.assertEqual(self.status()['conditions']['downloaded']['state'], 'UNKNOWN')
        self.private(self.destination / fact['name'], b'corrupt')
        self.assertEqual(self.status()['conditions']['created']['state'], 'UNKNOWN')
        (self.destination / fact['name']).unlink()
        self.assertEqual(self.status()['conditions']['downloaded']['state'], 'UNKNOWN')

    def test_application_and_foreign_instance_are_not_trusted(self):
        self.record(self.point())
        result = self.book.status('f'*40, self.image, self.destination, mode='mac', identity_file=self.key, now=self.now)
        self.assertEqual(result['conditions']['downloaded']['state'], 'UNKNOWN')
        with self.assertRaises(ValueError):
            self.book.record('created', self.point(project='adc_g4_222222222222'), now=self.now)

    def test_missing_receipts_and_unverified_restore_stay_unknown(self):
        self.assertTrue(all(v['state']=='UNKNOWN' for v in self.status()['conditions'].values()))
        with self.assertRaises(ValueError):
            self.book.record('restored', self.point(), now=self.now)

    def test_clock_and_original_manifest_time_cannot_be_rewritten(self):
        fact = self.point()
        for change in ({'created_at':(self.now+timedelta(hours=1)).isoformat()}, {'created_at':'2026-10-18T12:00:00'}, {'size':True}):
            with self.subTest(change=change), self.assertRaises((ValueError, TypeError)):
                self.book.record('created', fact|change, now=self.now)
        meta = dict(project=self.project, source_commit=self.source, images={'app':self.image}, created_at=self.now.isoformat())
        with self.assertRaises(ValueError):
            artifact(meta, fact)

    def test_legacy_manifest_time_is_readable_but_not_a_verified_capture_time(self):
        fact = self.point() | {'point_basis':'LEGACY_ARCHIVE_CREATION'}
        self.record(fact)
        self.assertEqual(self.status()['conditions']['downloaded']['state'], 'UNKNOWN')

    def test_conflicting_same_point_and_boolean_schema_refused(self):
        fact = self.point();self.record(fact)
        with self.assertRaises(ValueError):
            self.book.record('created', fact|{'sha256':'c'*64}, now=self.now)
        state = self.book.load();state['v']=True;self.book.store.write('receipts.json',state)
        self.assertEqual(self.status()['conditions']['created']['reason'], 'RECEIPTS_INVALID')

    def test_corrupt_envelope_and_foreign_private_state_cannot_be_healthy(self):
        self.record(self.point());path=self.book.store.directory/'receipts.json'
        data=json.loads(path.read_text());data['sha256']='0'*64;path.write_text(json.dumps(data))
        self.assertTrue(all(v['state']=='UNKNOWN' for v in self.status()['conditions'].values()))

    def test_history_is_bounded_and_pruning_is_explicit(self):
        fact=self.point()
        for i in range(101):
            self.book.record('created',fact,now=self.now+timedelta(seconds=i))
        state=self.book.load();self.assertEqual(len(state['history']),96);self.assertEqual(state['pruned_history'],5)

    def test_private_file_modes_symlinks_and_hard_links_refused(self):
        self.record(self.point());os.chmod(self.key,0o644)
        self.assertEqual(self.status()['conditions']['downloaded']['state'],'UNKNOWN')
        os.chmod(self.key,0o600);link=self.root/'alias';link.symlink_to(self.key)
        with self.assertRaises(ValueError):file_digest(link)
        hard=self.root/'hard';os.link(self.key,hard)
        with self.assertRaises(ValueError):file_digest(self.key)

    def test_thirty_utc_daily_copies_keep_latest_per_day(self):
        for days in range(35):
            for hour in (1,23):
                when=(self.now-timedelta(days=days)).replace(hour=hour)
                name='backup-'+when.strftime('%Y%m%dT%H%M%S%fZ')+'-'+self.project+'.tar.age'
                path=self.private(self.destination/name,b'ciphertext')
                row=dict(name=name,project=self.project,created_at=when.isoformat(),size=10,sha256=digest(path))
                self.private(self.destination/(name+'.json'),json.dumps(row).encode())
        prune_backups(self.destination,self.project,30)
        kept=backup_inventory(self.destination,self.project)
        self.assertEqual(len(kept),30)
        self.assertTrue(all('T230000' in row['name'] for row in kept))
        self.assertEqual({row['name'][7:15] for row in kept},{(self.now-timedelta(days=i)).strftime('%Y%m%d') for i in range(30)})


class SyncVerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.project='adc_g4_111111111111';self.source='a'*40;self.image='sha256:'+'b'*64
        self.remote=Remote.__new__(Remote)
        self.remote.plan={'project':self.project,'requested_source_commit':self.source,'images':{'app':self.image}}
        self.remote.remote_bundle='/srv/adc-course/releases/unit/.g4';self.remote.log=self.root/'private.log'
        self.destination=self.root/'mac';self.destination.mkdir(mode=0o700)
        self.key=self.root/'identity';self.key.write_bytes(b'current-key');os.chmod(self.key,0o600)
        self.rows=[];self.files={}
        self.remote.operation=Mock(side_effect=lambda name:{'project':self.project,'backups':list(self.rows)})
        def copy(source,target,**kw):
            shutil.copyfile(self.files[Path(target).name],source)
            os.chmod(source,0o600)  # Actual pinned-SSH copy creates owner-only files.
        self.remote.copy=Mock(side_effect=copy)
        self.now=datetime.now(timezone.utc)

    def add_archive(self,hours,**updates):
        created=self.now-timedelta(hours=hours)
        name='backup-'+created.strftime('%Y%m%dT%H%M%S%fZ')+'-'+self.project+'.tar.age'
        data=b'PGDMP synthetic'
        meta=dict(format=1,project=self.project,server_major=17,source_commit=self.source,
                  created_at=created.isoformat(),recovery_point_basis='BACKUP_START_CONSERVATIVE',images={'app':self.image},
                  files={'database.dump':{'sha256':hashlib.sha256(data).hexdigest(),'size':len(data)}})
        meta.update(updates)
        path=self.root/name
        with tarfile.open(path,'w') as archive:
            for entry,raw in [('database.dump',data),('archive.json',json.dumps(meta).encode())]:
                info=tarfile.TarInfo(entry);info.size=len(raw);archive.addfile(info,io.BytesIO(raw))
        os.chmod(path,0o600);self.files[name]=path
        self.rows.append(dict(name=name,project=self.project,created_at=created.isoformat(),size=path.stat().st_size,sha256=digest(path)))
        return self.rows[-1]

    def fake_decrypt(self,command,*args,**kwargs):
        shutil.copyfile(command[-1],command[command.index('-o')+1])

    def sync(self):
        with patch('scripts.g4_course.run',side_effect=self.fake_decrypt):
            return self.remote.sync(self.destination,self.key)

    def before(self):
        return {str(p.relative_to(self.destination)):p.read_bytes() for p in self.destination.rglob('*') if p.is_file() and not p.name.endswith('.lock')}

    def test_download_and_cached_reverification_preserve_original_time(self):
        row=self.add_archive(2);self.sync();copies=self.remote.copy.call_count
        result=self.sync();self.assertEqual(self.remote.copy.call_count,copies)
        self.assertEqual(result['last_off_host_backup'],row['created_at'])
        self.assertEqual(ReceiptBook(self.destination/'recovery',self.project).load()['latest']['downloaded']['artifact']['created_at'],row['created_at'])

    def test_forged_sidecar_time_never_advances_receipt(self):
        self.add_archive(3);self.sync();before=self.before()
        row=self.add_archive(1);row['created_at']=self.now.isoformat()
        with self.assertRaises(ValueError):self.sync()
        self.assertEqual(before,self.before())

    def test_later_corrupt_item_leaves_entire_batch_and_prior_receipts_unchanged(self):
        self.add_archive(4);self.sync();before=self.before()
        self.add_archive(2);row=self.add_archive(1);row['sha256']='f'*64
        with patch('scripts.g4_remote.prune_backups') as prune:
            with self.assertRaises(ValueError):self.sync()
            prune.assert_not_called()
        self.assertEqual(before,self.before())

    def test_wrong_current_key_on_cache_does_not_advance_or_prune(self):
        self.add_archive(1);self.sync();before=self.before()
        with patch('scripts.g4_course.run',side_effect=RuntimeError('wrong key')),patch('scripts.g4_remote.prune_backups') as prune:
            with self.assertRaises(RuntimeError):self.remote.sync(self.destination,self.key)
            prune.assert_not_called()
        self.assertEqual(before,self.before())

    def test_interrupted_transfer_does_not_replace_valid_archive(self):
        self.add_archive(4);self.sync();before=self.before();self.add_archive(1)
        def interrupted(path,*a,**kw):
            path.write_bytes(b'partial');raise RuntimeError('interrupted')
        self.remote.copy.side_effect=interrupted
        with self.assertRaises(RuntimeError):self.sync()
        self.assertEqual(before,self.before())

    def test_unsorted_inventory_uses_latest_original_point(self):
        latest=self.add_archive(1);self.add_archive(5)
        result=self.sync();self.assertEqual(result['sha256'],latest['sha256'])

    def test_duplicate_inventory_wrong_source_image_and_future_time_refused(self):
        for update in ({'source_commit':'f'*40},{'images':{'app':'sha256:'+'c'*64}},{'created_at':(self.now+timedelta(hours=1)).isoformat()}):
            self.rows.clear();self.add_archive(2,**update)
            with self.subTest(update=update),self.assertRaises(ValueError):self.sync()
        self.rows.clear();row=self.add_archive(1);self.rows.append(row)
        with self.assertRaises(ValueError):self.sync()


if __name__=='__main__':
    unittest.main()
