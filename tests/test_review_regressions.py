"""Focused regressions for release evidence, catalog validation, and browser saves.

Fixtures use temporary files and the existing isolated test approval store. No donor
runtime, real approval authority, or project return point is modified.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from portfolio_suites import catalog, registry, release_state
from portfolio_suites.recovery_program import load_recovery_program
from tests import test_release_state as release_fixtures


class ReleaseReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        self.ledger = release_state.load_release_ledger()
        self.program = load_recovery_program()
        self.suites = registry.load_suites()

    def test_missing_null_and_empty_dependencies_cannot_unlock_b1(self):
        for mode in ('missing', 'null', 'empty'):
            with self.subTest(mode=mode):
                ledger = deepcopy(self.ledger)
                blocker = next(b for b in ledger['release_blockers'] if 'brand-publishing/B1' in b['obligation_refs'])
                if mode == 'missing':
                    del blocker['depends_on']
                else:
                    blocker['depends_on'] = None if mode == 'null' else []
                errors = release_state.validate_release_ledger(ledger, self.program, self.suites)
                self.assertTrue(any('depends_on' in e or 'missing governed dependencies' in e for e in errors), errors)
                with self.assertRaises(release_state.ReleaseLedgerError):
                    release_state.resolve_release_state(ledger, self.program, self.suites)

    def test_authored_depth_cannot_promote_unexecuted_suite(self):
        for phase in ('beta', 'release-candidate', 'supported'):
            with self.subTest(phase=phase):
                ledger = deepcopy(self.ledger)
                ledger['suites']['brand-publishing'].update(
                    release_phase=phase, release_phase_owner='ryan', recovery_depth='source_executed')
                errors = release_state.validate_release_ledger(ledger, self.program, self.suites)
                self.assertTrue(any('no validated retained execution evidence' in e for e in errors), errors)

    def test_claimed_depth_cannot_exceed_validated_receipts(self):
        ledger = deepcopy(self.ledger)
        ledger['suites']['operator-os'].update(
            release_phase='supported', release_phase_owner='ryan', recovery_depth='parity_verified')
        errors = release_state.validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(any('no validated retained execution evidence' in e for e in errors), errors)

    def test_missing_execution_receipts_prevent_support_promotion(self):
        ledger = deepcopy(self.ledger)
        ledger['suites']['operator-os'].update(
            release_phase='supported', release_phase_owner='ryan', recovery_depth='source_executed')
        suites = deepcopy(self.suites)
        for wave in suites['operator-os']['waves']:
            if wave['id'] in ('O1', 'O4'):
                wave['evidence'] = 'operator-os/evidence/MISSING-' + wave['id'] + '.json'
        errors = release_state.validate_release_ledger(ledger, self.program, suites)
        self.assertTrue(any('support-promise evidence cannot be verified' in e for e in errors), errors)

    def retirement_fixture(self):
        fixture = release_fixtures.ReleaseLedgerTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        receipt, store = fixture._create_genuine_retirement_approval()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'retirement.json'
        path.write_text(json.dumps(receipt))
        ref = 'accessibility/evidence/REVIEW-RETIREMENT.json'
        ledger = deepcopy(self.ledger)
        ledger['suites']['accessibility'].update(
            release_phase='retired', release_phase_owner='ryan',
            retirement={'owner':'ryan', 'evidence_ref':ref, 'disposition':receipt['disposition']})
        self.enterContext(patch.dict('os.environ', {'PORTFOLIO_OPERATOR_APPROVAL_STORE':str(store)}))
        self.enterContext(fixture._mock_evidence_resolver(ref, path, expected_suite_id='accessibility'))
        return ledger, receipt, path

    def test_retirement_support_bytes_cannot_change_under_old_approval(self):
        ledger, receipt, _ = self.retirement_fixture()
        self.assertEqual(release_state.validate_release_ledger(ledger, self.program, self.suites), [])
        supporting = receipt['supporting_evidence_refs'][0]
        original = release_state._read_confined_suites_file
        with patch.object(release_state, '_read_confined_suites_file',
                          side_effect=lambda ref: (b'not a receipt', None) if ref == supporting else original(ref)):
            errors = release_state.validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(any('supporting evidence digest mismatch' in e for e in errors), errors)

    def test_supporting_receipt_contract_and_approval_digest_are_both_checked(self):
        ledger, receipt, path = self.retirement_fixture()
        supporting = receipt['supporting_evidence_refs'][0]
        bad_path = path.parent / 'invalid-support.json'
        bad_path.write_text('this is not a receipt')
        receipt['supporting_evidence_sha256'][supporting] = hashlib.sha256(bad_path.read_bytes()).hexdigest()
        path.write_text(json.dumps(receipt))
        original_resolve = registry.resolve_declared_evidence_path
        original_read = release_state._read_confined_suites_file
        with patch.object(registry, 'resolve_declared_evidence_path',
                          side_effect=lambda ref, suite_id=None: bad_path if ref == supporting else original_resolve(ref, suite_id)), \
             patch.object(release_state, '_read_confined_suites_file',
                          side_effect=lambda ref: (bad_path.read_bytes(), None) if ref == supporting else original_read(ref)):
            errors = release_state.validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(any('retirement supporting evidence ' + supporting + ':' in e for e in errors), errors)
        self.assertTrue(any('payload_sha256 does not bind exact retirement payload' in e for e in errors), errors)

    def test_retirement_legacy_path_only_approval_is_refused(self):
        ledger, receipt, path = self.retirement_fixture()
        del receipt['supporting_evidence_sha256']
        path.write_text(json.dumps(receipt))
        errors = release_state.validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(any('supporting_evidence_sha256 must bind' in e for e in errors), errors)

    def test_malformed_global_outcomes_return_errors(self):
        for outcome in ([], {}, 123, True):
            with self.subTest(outcome=outcome):
                ledger = deepcopy(self.ledger)
                ledger['global_blockers'][0]['closure'] = {'owner':'ryan', 'outcome':outcome}
                errors = release_state.validate_release_ledger(ledger, self.program, self.suites)
                self.assertTrue(any('closure outcome' in e for e in errors), errors)

    def test_malformed_retirement_decisions_operations_and_support_return_errors(self):
        ledger, receipt, path = self.retirement_fixture()
        for field in ('decision', 'operation', 'supporting_evidence_refs', 'supporting_evidence_sha256'):
            for value in ([], {}, ['valid', 12], True):
                with self.subTest(field=field, value=value):
                    bad = deepcopy(receipt)
                    if field == 'operation':
                        bad['approval'][field] = value
                    else:
                        bad[field] = value
                    path.write_text(json.dumps(bad))
                    self.assertTrue(release_state.validate_release_ledger(ledger, self.program, self.suites))


class CatalogReviewRegressionTests(unittest.TestCase):
    def test_alias_labels_are_required_strings(self):
        ledger = registry.load_ledger()
        name = ledger['projects'][0]['name']
        for label in (None, [], {}, 1, '', '   '):
            with self.subTest(label=label):
                ledger['catalog']['app_entries'] = [{'project':name, 'label':label}]
                self.assertIn('app entry requires a nonempty label', catalog.validate_catalog(ledger))
        ledger['catalog']['app_entries'] = [{'project':name}]
        self.assertIn('app entry requires a nonempty label', catalog.validate_catalog(ledger))

    def test_optional_alias_metadata_cannot_crash_exact_identity_resolution(self):
        ledger = registry.load_ledger()
        name = ledger['projects'][0]['name']
        ledger['catalog']['app_entries'] = [{'project':name}, {'project':name, 'label':[]}, None]
        self.assertEqual(catalog.resolve_project(name, ledger)['name'], name)


class BrowserReviewRegressionTests(unittest.TestCase):
    def test_deferred_saves_and_shared_release_queue(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node is required for these focused browser-logic checks.')
        result = subprocess.run(
            [node, str(Path(__file__).with_suffix('.js'))],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
