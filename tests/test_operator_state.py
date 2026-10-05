import copy
import hashlib
import json
import os
import unittest
from unittest.mock import patch

from portfolio_suites import catalog, operator_state as state, registry
from portfolio_suites.paths import CommitUnverified
from portfolio_suites.txn import CommitUncertain, OccupantConflict
from tests.test_catalog import CatalogFixture


class OperatorStateTests(CatalogFixture, unittest.TestCase):
    def test_preview_restore_and_undo_preserve_release_fields_and_revisions(self):
        saved = state.manage_state('backup')['backup']
        catalog.update_project('alpha', {'attention': 'now', 'next_action': 'Finish one page.'})
        before = self.path.read_bytes()
        self.assertEqual(state.manage_state('restore', saved)['changed'], ['alpha'])
        self.assertEqual(before, self.path.read_bytes())
        result = state.manage_state('restore', saved, apply=True)
        self.assertEqual(result['status'], 'restored')
        restored = registry.load_ledger()
        self.assertIsNone(restored['projects'][0]['operator']['attention'])
        self.assertEqual(restored['projects'][0]['operator']['revision'], 2)
        for old, new in zip(self.doc['projects'], restored['projects']):
            self.assertEqual({k:v for k,v in old.items() if k != 'operator'},
                             {k:v for k,v in new.items() if k != 'operator'})
        state.manage_state('restore', result['undo_backup'], apply=True)
        self.assertEqual(catalog.resolve_project('alpha')['operator']['next_action'], 'Finish one page.')
        self.assertEqual(catalog.resolve_project('alpha')['operator']['revision'], 3)

    def test_restore_does_not_refresh_stale_resume_observation(self):
        backup = state.make_backup(self.doc)
        original = copy.deepcopy(self.doc['projects'][0]['operator']['resume'])
        from pathlib import Path
        Path(original['target']).write_text('changed after backup')
        self.doc['projects'][0]['operator']['resume'] = None
        result, _ = state.restore_document(self.doc, backup)
        op = result['projects'][0]['operator']
        self.assertEqual(op['resume'], original)
        self.assertEqual(catalog.resume_status(op)['state'], 'changed')

    def test_corrupt_unknown_version_and_identity_changes_are_refused(self):
        backup = state.make_backup(self.doc)
        for mutation in ('digest', 'version', 'identity', 'owner', 'fields', 'waiting', 'now_limit'):
            with self.subTest(mutation=mutation):
                bad = copy.deepcopy(backup)
                if mutation == 'digest': bad['payload_sha256'] = '0' * 64
                elif mutation == 'version': bad['schema_version'] = 'portfolio-operator-backup-v99'
                elif mutation == 'identity': del bad['projects']['alpha']
                elif mutation == 'owner': bad['projects']['alpha']['owner'] = 'someone else'
                elif mutation == 'fields': bad['projects']['alpha']['fields']['disposition'] = 'retired'
                elif mutation == 'waiting': bad['projects']['alpha']['fields'].update(attention='waiting', waiting_trigger=None)
                elif mutation == 'now_limit':
                    for index, row in enumerate(bad['projects'].values(), 1):
                        row['fields'].update(attention='now', now_order=index)
                if mutation != 'digest':
                    bad['payload_sha256'] = hashlib.sha256(state._canonical(bad['projects'])).hexdigest()
                with self.assertRaises(catalog.CatalogError): state.restore_document(self.doc, bad)

    def test_partial_legacy_state_requires_reconciliation_not_invented_migration(self):
        legacy = copy.deepcopy(self.doc)
        del legacy['catalog']
        with self.assertRaisesRegex(catalog.CatalogError, 'reconciled'): state.make_backup(legacy)
        with self.assertRaises(catalog.CatalogError): state.make_backup(None)

    def test_latest_backup_needs_no_filename_and_is_preview_only(self):
        saved = state.manage_state('backup')['backup']
        catalog.update_project('alpha', {'next_action': 'Current action.'})
        before = self.path.read_bytes()
        result = state.manage_state('restore')
        self.assertEqual(result['backup'], saved)
        self.assertEqual(result['status'], 'preview')
        self.assertEqual(result['changed'], ['alpha'])
        self.assertEqual(before, self.path.read_bytes())

    def test_conflict_and_uncertain_commit_keep_undo_and_distinct_outcomes(self):
        saved = state.manage_state('backup')['backup']
        catalog.update_project('alpha', {'next_action': 'Keep this change.'})
        before = self.path.read_bytes()
        for exception, expected in ((OccupantConflict('raced'), catalog.CatalogConflict),
                                    (CommitUncertain('uncertain'), CommitUnverified)):
            with patch.object(state, 'commit_replacement', side_effect=exception):
                with self.assertRaisesRegex(expected, 'Undo backup'): state.manage_state('restore', saved, apply=True)
            self.assertEqual(before, self.path.read_bytes())
        self.assertGreaterEqual(len(list((self.suites/state.DIRECTORY).glob('*.json'))), 3)

    def test_backup_paths_symlinks_and_hardlinks_are_refused(self):
        saved = state.manage_state('backup')['backup']
        with self.assertRaises(catalog.CatalogError): state.manage_state('restore', '../' + saved)
        path = self.suites/state.DIRECTORY/saved
        data = path.read_bytes()
        path.unlink(); path.symlink_to(self.path)
        with self.assertRaises(OSError): state.manage_state('restore', saved)
        path.unlink(); path.write_bytes(data)
        os.link(path, path.with_suffix('.link'))
        with self.assertRaises(catalog.CatalogError): state.manage_state('restore', saved)
