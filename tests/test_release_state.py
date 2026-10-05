from __future__ import annotations

import hashlib
import json
from typing import Any
import unittest
from copy import deepcopy
from pathlib import Path
import tempfile
from tempfile import TemporaryDirectory
from unittest import mock

from portfolio_suites.release_state import (
    load_release_ledger,
    release_state_summary,
    resolve_release_state,
    validate_release_ledger,
)
from portfolio_suites.recovery_program import load_recovery_program
from portfolio_suites.registry import load_suites


class ReleaseLedgerTests(unittest.TestCase):
    """Validate the release ledger fails closed on the exact mis-declarations the
    roadmap names (docs/ROADMAP.md: Item 1, negative tests at line 183)."""

    def setUp(self):
        self.ledger = load_release_ledger()
        self.program = load_recovery_program()
        self.suites = load_suites()

    def _minimal_criterion(self, suite_id="accessibility", status="open"):
        return {
            "id": f"{suite_id}.test-criterion",
            "name": "test criterion",
            "obligation_refs": [{"id": f"{suite_id}/A1"}],
            "status": status,
        }

    def test_baseline_ledger_is_valid(self):
        self.assertEqual(validate_release_ledger(self.ledger, self.program, self.suites), [])

    def test_ledger_cannot_omit_registered_suites(self):
        # Dropping a registered suite from the ledger could hide its weakest gates and
        # report release_ready anyway -- the suite set must match the registry exactly.
        ledger = deepcopy(self.ledger)
        ledger["suites"] = {
            sid: block
            for sid, block in ledger["suites"].items()
            if sid == "brand-publishing"
        }
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("omits registered suites" in error for error in errors),
            errors,
        )

    def test_ledger_rejects_unknown_suite(self):
        ledger = deepcopy(self.ledger)
        ledger["suites"]["not-a-suite"] = {
            "release_phase": "alpha",
            "release_phase_owner": None,
            "score_status": "insufficient_dimension_evidence",
            "score": None,
            "criteria": [self._minimal_criterion("brand-publishing")],
        }
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("unknown suites" in error for error in errors),
            errors,
        )

    def test_criterion_requires_nonempty_obligation_refs(self):
        # A criterion that owns no obligation could not move a release gate and would
        # silently satisfy with a name -- it must be rejected.
        ledger = deepcopy(self.ledger)
        criterion = ledger["suites"]["brand-publishing"]["criteria"][0]
        criterion["obligation_refs"] = []
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("non-empty list" in error for error in errors),
            errors,
        )

    def test_string_form_obligation_ref_is_rejected(self):
        # The design document previously showed refs as strings; the implementation
        # consumes objects. A config following the stale doc would make a criterion
        # govern nothing -- string refs fail closed.
        ledger = deepcopy(self.ledger)
        criterion = ledger["suites"]["brand-publishing"]["criteria"][0]
        criterion["obligation_refs"] = ["brand-publishing/B1"]
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("must be an object with an id" in error for error in errors),
            errors,
        )

    def test_governed_obligation_must_be_covered_by_a_criterion(self):
        # Every obligation the recovery program governs must be owned by at least one
        # criterion, or it is invisible to the release gates and could never block.
        ledger = deepcopy(self.ledger)
        ledger["suites"]["accessibility"]["criteria"] = [
            ledger["suites"]["accessibility"]["criteria"][1]
        ]
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("does not cover governed obligations" in error for error in errors),
            errors,
        )

    def test_impossible_promotion_refused(self):
        # Even an owner-backed support promise cannot claim a supportable depth below
        # source_executed: owner authority vouches for the disposition, not for having
        # executed real evidence (DESIGN §3, MIN_SUPPORT_PROMISE_LEVEL).
        ledger = deepcopy(self.ledger)
        ledger["suites"]["brand-publishing"]["release_phase"] = "supported"
        ledger["suites"]["brand-publishing"]["release_phase_owner"] = "ryan"
        ledger["suites"]["brand-publishing"]["recovery_depth"] = "prototype"
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("cannot claim depth prototype" in error for error in errors),
            errors,
        )

    def test_ownerless_support_promise_is_refused(self):
        # A support promise is an owner-backed declaration; an anonymous suite must not
        # claim "supported" even with a defensible depth.
        ledger = deepcopy(self.ledger)
        ledger["suites"]["brand-publishing"]["release_phase"] = "beta"
        ledger["suites"]["brand-publishing"]["release_phase_owner"] = None
        ledger["suites"]["brand-publishing"]["recovery_depth"] = "source_executed"
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("requires a release_phase_owner" in error for error in errors),
            errors,
        )

    def test_owner_backed_support_promise_at_source_executed_is_accepted(self):
        ledger = deepcopy(self.ledger)
        ledger["suites"]["brand-publishing"]["release_phase"] = "supported"
        ledger["suites"]["brand-publishing"]["release_phase_owner"] = "ryan"
        ledger["suites"]["brand-publishing"]["recovery_depth"] = "source_executed"
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertNotIn(
            "cannot claim depth", " ".join(errors), errors,
        )
        self.assertNotIn(
            "requires a release_phase_owner", " ".join(errors), errors,
        )

    def test_closure_requires_owner_and_evidence(self):
        ledger = deepcopy(self.ledger)
        suite = ledger["suites"]["brand-publishing"]
        criterion = suite["criteria"][0]
        criterion["status"] = "closed"
        criterion["closure"] = {"outcome": "implemented"}
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("closure evidence_ref must resolve" in error for error in errors),
            errors,
        )
        self.assertTrue(
            any("requires a non-empty owner" in error for error in errors),
            errors,
        )

    def test_evidence_ref_escaping_suite_is_refused(self):
        ledger = deepcopy(self.ledger)
        criterion = ledger["suites"]["brand-publishing"]["criteria"][0]
        criterion["status"] = "closed"
        criterion["closure"] = {
            "outcome": "implemented",
            "owner": "ryan",
            "evidence_ref": "../other-suite/evidence/x.json",
        }
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("must resolve to the canonical" in error for error in errors),
            errors,
        )

    def test_closure_evidence_ref_missing_on_disk_is_refused(self):
        ledger = deepcopy(self.ledger)
        criterion = ledger["suites"]["accessibility"]["criteria"][0]
        criterion["status"] = "closed"
        criterion["closure"] = {
            "outcome": "implemented",
            "owner": "ryan",
            "evidence_ref": "accessibility/evidence/NOT-ON-DISK.json",
        }
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("missing on disk" in error for error in errors),
            errors,
        )

    def test_closure_evidence_ref_to_real_artifact_is_accepted(self):
        # A closure over a valid governed receipt (accessibility.v1.adoption owns the
        # A2-adoption obligation, and A2-ADOPTION.json passes its adoption validator)
        # is accepted end to end.
        ledger = deepcopy(self.ledger)
        criterion = ledger["suites"]["accessibility"]["criteria"][1]
        criterion["status"] = "closed"
        criterion["closure"] = {
            "outcome": "implemented",
            "owner": "ryan",
            "evidence_ref": "accessibility/evidence/A2-ADOPTION.json",
        }
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertNotIn(
            "closure evidence_ref", " ".join(errors), errors,
        )

    def test_closure_evidence_empty_object_is_refused(self):
        # An empty JSON object must not pass as implementation evidence: existence and
        # object shape prove neither provenance nor the claimed closure. The governed
        # receipt validator rejects it (F3).
        ledger = deepcopy(self.ledger)
        criterion = ledger["suites"]["accessibility"]["criteria"][1]
        criterion["status"] = "closed"
        criterion["closure"] = {
            "outcome": "implemented",
            "owner": "ryan",
            "evidence_ref": "accessibility/evidence/NOT-ON-DISK-BUT-EMPTY.json",
        }
        from portfolio_suites.registry import resolve_declared_evidence_path
        import tempfile, pathlib
        fake = pathlib.Path(tempfile.mkstemp(suffix=".json")[1])
        fake.write_text("{}")
        with mock.patch(
            "portfolio_suites.registry.resolve_declared_evidence_path", return_value=fake
        ):
            errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("fails every governed receipt validator" in error for error in errors),
            errors,
        )

    def test_closure_evidence_wrong_contract_is_refused(self):
        # An adoption receipt cited on a runtime-parity criterion is a contract mismatch:
        # the governed receipt validator for the parity obligations must reject it.
        ledger = deepcopy(self.ledger)
        criterion = ledger["suites"]["accessibility"]["criteria"][0]
        criterion["status"] = "closed"
        criterion["closure"] = {
            "outcome": "implemented",
            "owner": "ryan",
            "evidence_ref": "accessibility/evidence/A2-ADOPTION.json",
        }
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("fails every governed receipt validator" in error for error in errors),
            errors,
        )

    def test_resolved_without_owner_is_forbidden(self):
        ledger = deepcopy(self.ledger)
        criterion = ledger["suites"]["brand-publishing"]["criteria"][0]
        criterion["status"] = "closed"
        criterion["closure"] = {
            "outcome": "implemented",
            "evidence_ref": "brand-publishing/evidence/x.json",
        }
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("non-empty owner" in error for error in errors),
            errors,
        )

    def test_blanket_deferral_requires_trigger(self):
        ledger = deepcopy(self.ledger)
        criterion = ledger["suites"]["brand-publishing"]["criteria"][0]
        criterion["status"] = "closed"
        criterion["closure"] = {"outcome": "deferred_with_trigger", "owner": "ryan"}
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("resume_trigger" in error for error in errors),
            errors,
        )

    def test_unknown_obligation_ref_is_refused(self):
        ledger = deepcopy(self.ledger)
        ledger["suites"]["brand-publishing"]["criteria"][0]["obligation_refs"] = [
            {"id": "brand-publishing/DOES-NOT-EXIST"}
        ]
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("unknown obligation_ref" in error for error in errors),
            errors,
        )

    def test_cross_suite_obligation_ref_is_refused(self):
        ledger = deepcopy(self.ledger)
        ledger["suites"]["brand-publishing"]["criteria"][0]["obligation_refs"] = [
            {"id": "accessibility/A1"}
        ]
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("belongs to another suite" in error for error in errors),
            errors,
        )

    def test_duplicate_criterion_id_is_refused(self):
        # Two criteria sharing an id would let one silently mask the other's open state.
        ledger = deepcopy(self.ledger)
        criteria = ledger["suites"]["brand-publishing"]["criteria"]
        criteria.append(deepcopy(criteria[0]))
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("duplicate criterion id" in error for error in errors),
            errors,
        )

    def test_open_criterion_must_not_carry_closure(self):
        ledger = deepcopy(self.ledger)
        criterion = ledger["suites"]["brand-publishing"]["criteria"][0]
        criterion["status"] = "open"
        criterion["closure"] = {"outcome": "implemented", "owner": "ryan"}
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("open criterion must not carry a closure" in error for error in errors),
            errors,
        )

    def test_score_stays_null_without_dimension_evidence(self):
        summary = release_state_summary(self.ledger, self.program, self.suites)
        state = resolve_release_state(self.ledger, self.program, self.suites)
        for suite_id, row in state["suites"].items():
            self.assertIsNone(row["score"])
            self.assertEqual(row["score_status"], "insufficient_dimension_evidence")
        self.assertFalse(summary["has_no_blockers"])

    def test_numeric_score_requires_computed_status(self):
        # An authored number is false precision until the control plane derives a score
        # from validated dimension evidence (registry.py:773). Any numeric score is
        # rejected regardless of its status pairing -- there is no valid authored number.
        ledger = deepcopy(self.ledger)
        ledger["suites"]["brand-publishing"]["score"] = 5.0
        ledger["suites"]["brand-publishing"]["score_status"] = "insufficient_dimension_evidence"
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("authored score" in error for error in errors),
            errors,
        )

    def test_authored_numeric_score_rejected_even_with_computed_status(self):
        # Marking a manually typed number "computed" does not make it true; the
        # insufficient_dimension_evidence sentinel is the only valid status today.
        ledger = deepcopy(self.ledger)
        ledger["suites"]["brand-publishing"]["score"] = 9.5
        ledger["suites"]["brand-publishing"]["score_status"] = "computed"
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("no numeric score is accepted" in error for error in errors),
            errors,
        )
        self.assertTrue(
            any("authored score" in error for error in errors),
            errors,
        )
        with self.assertRaises(Exception):
            resolve_release_state(ledger, self.program, self.suites)

    def test_b1_held_until_contract_freeze_closed(self):
        state = resolve_release_state(self.ledger, self.program, self.suites)
        b1 = next(b for b in state["open_blockers"] if b["id"] == "brand-publishing.v1.b1-runtime")
        self.assertTrue(b1["open"])
        self.assertNotIn(
            b1["id"], {b["id"] for b in state["actionable_blockers"]}
        )

    def test_contract_freeze_is_actionable(self):
        state = resolve_release_state(self.ledger, self.program, self.suites)
        freeze = next(
            b for b in state["open_blockers"]
            if b["id"] == "phase1.contract-state-freeze"
        )
        self.assertIn(freeze["id"], {b["id"] for b in state["actionable_blockers"]})

    def test_blocker_dependency_chain_holds_runtime(self):
        ledger = deepcopy(self.ledger)
        for blocker in ledger["global_blockers"]:
            blocker["closure"] = None
        state = resolve_release_state(ledger, self.program, self.suites)
        b1 = next(b for b in state["open_blockers"] if b["id"] == "brand-publishing.v1.b1-runtime")
        self.assertNotIn(b1["id"], {b["id"] for b in state["actionable_blockers"]})

    def test_bare_closed_boolean_is_refused_not_authority(self):
        # F1 regression: a bare "closed": true flag must not authorize dependent work.
        # A phase-boundary gate closes only through an evidence- and owner-bound closure
        # record; flipping a boolean is rejected before it can unblock anything held on it.
        for desired in (True, False):
            ledger = deepcopy(self.ledger)
            for blocker in ledger["global_blockers"]:
                blocker["closed"] = desired
            errors = validate_release_ledger(ledger, self.program, self.suites)
            self.assertTrue(
                any("bare 'closed' flag is not valid" in error for error in errors),
                f"desired={desired}: {errors}",
            )
            with self.assertRaises(Exception):
                resolve_release_state(ledger, self.program, self.suites)

    def _create_global_closure_receipt(self, blocker_id: str, owner: str = "ryan", custom_receipt: dict = None):
        import json, tempfile
        from pathlib import Path
        from portfolio_suites.release_state import (
            GLOBAL_BLOCKER_SPECS,
            GLOBAL_CLOSURE_RECEIPT_CONTRACT,
            canonical_suites_file_digest,
        )
        from portfolio_suites.paths import SUITES_ROOT

        spec = GLOBAL_BLOCKER_SPECS[blocker_id]
        frozen = {}
        for surface, paths in spec.items():
            frozen[surface] = [
                {"path": p, "sha256": canonical_suites_file_digest(p, SUITES_ROOT.joinpath(p).read_bytes())}
                for p in sorted(paths)
            ]
        doc = {
            "receipt_version": GLOBAL_CLOSURE_RECEIPT_CONTRACT,
            "blocker_id": blocker_id,
            "owner": owner,
            "outcome": "implemented",
            "frozen_boundaries": frozen,
        }
        if custom_receipt is not None:
            doc = custom_receipt
        tmp = tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False)
        json.dump(doc, tmp)
        tmp.close()
        receipt_path = Path(tmp.name)
        self.addCleanup(receipt_path.unlink, missing_ok=True)
        return frozen, receipt_path

    def _mock_evidence_resolver(self, target_ref: str, target_path: Path, expected_suite_id: Any = None):
        from portfolio_suites.registry import resolve_declared_evidence_path as orig_resolve

        def resolver(ref, suite_id=None):
            if ref == target_ref and (expected_suite_id is None or suite_id == expected_suite_id):
                return target_path
            return orig_resolve(ref, suite_id)

        return mock.patch("portfolio_suites.registry.resolve_declared_evidence_path", side_effect=resolver)

    def test_global_closure_with_owner_evidence_and_matching_boundaries_is_accepted(self):
        # F1 positive control: a gate closes only through a valid evidence- and
        # owner-bound closure whose frozen-boundary digests still match current bytes.
        # This verifies a persisted round trip: serializing the closed ledger to a real file,
        # reloading from that persisted file, and verifying validation and resolution
        # without mutating the tracked checkout.
        import tempfile
        from portfolio_suites.release_state import _read_confined_suites_file as orig_read
        frozen, tmp_path = self._create_global_closure_receipt("phase0.release-ledger", owner="ryan")
        ref = "operator-os/evidence/GLOBAL-FREEZE-RECEIPT.json"
        ledger = deepcopy(self.ledger)
        ledger["global_blockers"][0]["closure"] = {
            "owner": "ryan",
            "outcome": "implemented",
            "evidence_ref": ref,
            "frozen_boundaries": frozen,
        }
        tmp_ledger = tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False)
        tmp_ledger.write(json.dumps(ledger, indent=2))
        tmp_ledger.close()
        tmp_ledger_path = Path(tmp_ledger.name)
        self.addCleanup(tmp_ledger_path.unlink, missing_ok=True)

        def mock_read_confined(path_text: str):
            if path_text == "portfolio/release-ledger.json":
                return tmp_ledger_path.read_bytes(), None
            return orig_read(path_text)

        persisted = load_release_ledger(tmp_ledger_path)
        with mock.patch("portfolio_suites.release_state._read_confined_suites_file", side_effect=mock_read_confined):
            with self._mock_evidence_resolver(ref, tmp_path):
                errors = validate_release_ledger(persisted, self.program, self.suites)
                self.assertEqual(errors, [], errors)
                state = resolve_release_state(persisted, self.program, self.suites)
        open_ids = {b["id"] for b in state["open_blockers"]}
        self.assertNotIn("phase0.release-ledger", open_ids)
        self.assertIn("phase0.release-ledger", state["closed_by_id"])
        self.assertTrue(state["closed_by_id"]["phase0.release-ledger"])

    def test_global_closure_rejects_tampered_non_closure_ledger_content(self):
        # F1 negative control: modifying non-closure ledger content (e.g. policy)
        # changes the canonical digest and invalidates phase0.release-ledger closure.
        # Verified without mutating the tracked checkout.
        import tempfile
        from portfolio_suites.release_state import _read_confined_suites_file as orig_read
        frozen, tmp_path = self._create_global_closure_receipt("phase0.release-ledger", owner="ryan")
        ref = "operator-os/evidence/GLOBAL-FREEZE-RECEIPT.json"
        ledger = deepcopy(self.ledger)
        ledger["global_blockers"][0]["closure"] = {
            "owner": "ryan",
            "outcome": "implemented",
            "evidence_ref": ref,
            "frozen_boundaries": frozen,
        }
        tampered_ledger = deepcopy(ledger)
        tampered_ledger["policy"]["minimum_authentic_uses_for_adoption"] = 99
        tmp_tampered = tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False)
        tmp_tampered.write(json.dumps(tampered_ledger, indent=2))
        tmp_tampered.close()
        tmp_tampered_path = Path(tmp_tampered.name)
        self.addCleanup(tmp_tampered_path.unlink, missing_ok=True)

        def mock_read_confined_tampered(path_text: str):
            if path_text == "portfolio/release-ledger.json":
                return tmp_tampered_path.read_bytes(), None
            return orig_read(path_text)

        persisted = load_release_ledger(tmp_tampered_path)
        with mock.patch("portfolio_suites.release_state._read_confined_suites_file", side_effect=mock_read_confined_tampered):
            with self._mock_evidence_resolver(ref, tmp_path):
                errors = validate_release_ledger(persisted, self.program, self.suites)
            self.assertTrue(
                any("digest mismatch" in e and "portfolio/release-ledger.json" in e for e in errors),
                errors,
            )

    def test_global_closure_rejects_stale_frozen_boundary_digest(self):
        # F1: an evidence-backed closure whose frozen-boundary digest was computed on old
        # bytes must be refused, so dependent work cannot cross a boundary that moved.
        frozen, tmp_path = self._create_global_closure_receipt("phase0.release-ledger", owner="ryan")
        stale_frozen = deepcopy(frozen)
        stale_frozen["release_ledger"][0]["sha256"] = "0" * 64
        import json
        tmp_path.write_text(json.dumps({
            "receipt_version": "portfolio-global-closure-v1",
            "blocker_id": "phase0.release-ledger",
            "owner": "ryan",
            "outcome": "implemented",
            "frozen_boundaries": stale_frozen,
        }), encoding="utf-8")
        ref = "operator-os/evidence/GLOBAL-FREEZE-RECEIPT.json"
        ledger = deepcopy(self.ledger)
        ledger["global_blockers"][0]["closure"] = {
            "owner": "ryan",
            "outcome": "implemented",
            "evidence_ref": ref,
            "frozen_boundaries": stale_frozen,
        }
        with self._mock_evidence_resolver(ref, tmp_path):
            errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("digest mismatch" in error for error in errors),
            errors,
        )
        with self._mock_evidence_resolver(ref, tmp_path):
            with self.assertRaises(Exception):
                resolve_release_state(ledger, self.program, self.suites)

    def test_unknown_blocker_dependency_is_refused(self):
        ledger = deepcopy(self.ledger)
        ledger["release_blockers"][0]["depends_on"] = ["phase9.no-such-gate"]
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("depends_on unknown blocker" in error for error in errors),
            errors,
        )

    def test_release_blocker_requires_obligation_refs(self):
        # A release blocker with no dischargeable obligation would vanish from the release
        # gates without a closure record -- the exact silent-closure failure the module
        # forbids. It must be rejected, not accepted as permanently closed.
        ledger = deepcopy(self.ledger)
        ledger["release_blockers"].append(
            {"id": "suite.x.forgot-refs", "phase": "1", "name": "real work", "depends_on": []}
        )
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("requires a non-empty obligation_refs" in error for error in errors),
            errors,
        )

    def test_sub_target_score_is_rejected_until_derivation_exists(self):
        # A manually entered score has no provenance, so it cannot be trusted as an
        # in-progress blocker OR a satisfied target. It fails closed on entry: no
        # authored number survives validation today.
        ledger = deepcopy(self.ledger)
        ledger["suites"]["brand-publishing"]["score"] = 7.0
        ledger["suites"]["brand-publishing"]["score_status"] = "computed"
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("authored score" in error for error in errors),
            errors,
        )

    def test_global_blocker_depends_on_unknown_id_is_refused(self):
        # The unknown-dependency rule must cover both blocker lists: a typo'd gate
        # dependency silently drops that gate out of the actionable queue forever.
        ledger = deepcopy(self.ledger)
        ledger["global_blockers"][1]["depends_on"] = ["phase9.no-such-gate"]
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("depends_on unknown blocker" in error for error in errors),
            errors,
        )

    def test_blocker_dependency_cycle_is_refused(self):
        # A cycle leaves every blocker non-actionable with no closure record, which
        # reads as genuine remaining work rather than a ledger authoring bug.
        ledger = deepcopy(self.ledger)
        ledger["global_blockers"][1]["depends_on"] = ["phase1.stable-surface"]
        ledger["global_blockers"][2]["depends_on"] = ["phase1.contract-state-freeze"]
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("depends_on cycle" in error for error in errors),
            errors,
        )

    def test_blocker_self_dependency_is_refused(self):
        ledger = deepcopy(self.ledger)
        ledger["global_blockers"][1]["depends_on"] = ["phase1.contract-state-freeze"]
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("depends_on cycle" in error for error in errors),
            errors,
        )

    def test_release_ready_requires_scores_as_well_as_zero_blockers(self):
        # Zero blockers is half the v1 claim; suites short of their tier score target
        # keep the ledger not-release-ready.
        summary = release_state_summary(self.ledger, self.program, self.suites)
        self.assertFalse(summary["release_ready"])
        self.assertEqual(summary["suites_under_score_target"], len(self.ledger["suites"]))

    def test_global_blocker_id_collides_with_release_blocker(self):
        # Blocker ids must be unique across both lists so a global entry can never
        # silently shadow a release blocker of the same id.
        ledger = deepcopy(self.ledger)
        leaking = None
        for blocker in ledger["release_blockers"]:
            if blocker["id"] == "brand-publishing.v1.b1-runtime":
                leaking = blocker
                break
        ledger["global_blockers"].append(
            {"id": leaking["id"], "phase": "1", "name": "shadow", "depends_on": [], "closed": False}
        )
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("collides with a release blocker id" in error for error in errors),
            errors,
        )

    def test_release_ready_requires_all_criteria_closed(self):
        # Zero blockers plus at-target scores are not enough: an open v1 criterion that
        # no release blocker captures must still withhold release-ready.
        state = {
            "ledger_id": "portfolio-release-completion-v1",
            "suites": {
                "brand-publishing": {
                    "release_phase": "alpha",
                    "criteria_total": 1,
                    "criteria_closed": 1,
                    "criteria_open": 0,
                    "score_status": "computed",
                    "criteria": [],
                }
            },
            "open_blocker_count": 0,
            "actionable_blocker_count": 0,
        }
        with mock.patch(
            "portfolio_suites.release_state.resolve_release_state", return_value=state
        ):
            ready = release_state_summary(self.ledger, self.program, self.suites)
        self.assertTrue(ready["release_ready"])

        state["suites"]["brand-publishing"]["criteria_open"] = 1
        state["suites"]["brand-publishing"]["criteria_closed"] = 0
        with mock.patch(
            "portfolio_suites.release_state.resolve_release_state", return_value=state
        ):
            ready = release_state_summary(self.ledger, self.program, self.suites)
        self.assertFalse(ready["release_ready"])

    def test_non_string_blocker_name_and_note_are_refused(self):
        # name/note are rendered verbatim in CLI output, so a non-string value must be
        # a validation error, not silently printed.
        ledger = deepcopy(self.ledger)
        ledger["release_blockers"][0]["note"] = 5
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("note must be a string" in error for error in errors),
            errors,
        )

        ledger = deepcopy(self.ledger)
        ledger["global_blockers"][1]["name"] = {"broken": True}
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("name must be a string" in error for error in errors),
            errors,
        )

    def test_global_closure_empty_frozen_boundaries_is_refused(self):
        # F1 regression: empty frozen_boundaries must be rejected.
        ledger = deepcopy(self.ledger)
        ledger["global_blockers"][1]["closure"] = {
            "owner": "ryan",
            "outcome": "implemented",
            "evidence_ref": "operator-os/evidence/O1-SOURCE-RECORD-OBSERVER-PROJECTION.json",
            "frozen_boundaries": {},
        }
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("frozen_boundaries must be a non-empty object" in error for error in errors),
            errors,
        )

    def test_global_closure_unrelated_surface_is_refused(self):
        # F1 regression: arbitrary surface names and paths are refused.
        ledger = deepcopy(self.ledger)
        ledger["global_blockers"][1]["closure"] = {
            "owner": "ryan",
            "outcome": "implemented",
            "evidence_ref": "operator-os/evidence/O1-SOURCE-RECORD-OBSERVER-PROJECTION.json",
            "frozen_boundaries": {
                "unrelated": [{"path": "README.md", "sha256": "0" * 64}],
            },
        }
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("unpermitted surface" in error for error in errors),
            errors,
        )

    def test_global_closure_empty_receipt_is_refused(self):
        # F1 regression: an empty receipt object {} is refused as a global closure receipt.
        import tempfile
        from pathlib import Path
        tmp = tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False)
        tmp.write("{}")
        tmp.close()
        frozen, _ = self._create_global_closure_receipt("phase1.contract-state-freeze")
        ref = "operator-os/evidence/GLOBAL-FREEZE-RECEIPT.json"
        ledger = deepcopy(self.ledger)
        ledger["global_blockers"][1]["closure"] = {
            "owner": "ryan",
            "outcome": "implemented",
            "evidence_ref": ref,
            "frozen_boundaries": frozen,
        }
        with self._mock_evidence_resolver(ref, Path(tmp.name)):
            errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("receipt_version must equal 'portfolio-global-closure-v1'" in error for error in errors),
            errors,
        )

    def test_global_closure_receipt_blocker_id_mismatch_is_refused(self):
        # F1: receipt must bind the blocker ID.
        frozen, tmp_path = self._create_global_closure_receipt(
            "phase1.contract-state-freeze",
            custom_receipt={
                "receipt_version": "portfolio-global-closure-v1",
                "blocker_id": "other.blocker",
                "owner": "ryan",
                "outcome": "implemented",
                "frozen_boundaries": {},
            },
        )
        ref = "operator-os/evidence/GLOBAL-FREEZE-RECEIPT.json"
        ledger = deepcopy(self.ledger)
        ledger["global_blockers"][1]["closure"] = {
            "owner": "ryan",
            "outcome": "implemented",
            "evidence_ref": ref,
            "frozen_boundaries": frozen,
        }
        with self._mock_evidence_resolver(ref, tmp_path):
            errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("does not match blocker 'phase1.contract-state-freeze'" in error for error in errors),
            errors,
        )

    def test_global_closure_receipt_owner_mismatch_is_refused(self):
        # F1: receipt must bind the closure owner.
        frozen, tmp_path = self._create_global_closure_receipt(
            "phase1.contract-state-freeze",
            owner="wrong-owner",
        )
        ref = "operator-os/evidence/GLOBAL-FREEZE-RECEIPT.json"
        ledger = deepcopy(self.ledger)
        ledger["global_blockers"][1]["closure"] = {
            "owner": "ryan",
            "outcome": "implemented",
            "evidence_ref": ref,
            "frozen_boundaries": frozen,
        }
        with self._mock_evidence_resolver(ref, tmp_path):
            errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("does not match closure owner 'ryan'" in error for error in errors),
            errors,
        )

    def test_global_closure_duplicate_path_binding_is_refused(self):
        # F1: duplicate path bindings in a surface are refused.
        frozen, tmp_path = self._create_global_closure_receipt("phase1.contract-state-freeze")
        first_binding = frozen["contracts_schemas"][0]
        frozen["contracts_schemas"].append(first_binding)
        ref = "operator-os/evidence/GLOBAL-FREEZE-RECEIPT.json"
        ledger = deepcopy(self.ledger)
        ledger["global_blockers"][1]["closure"] = {
            "owner": "ryan",
            "outcome": "implemented",
            "evidence_ref": ref,
            "frozen_boundaries": frozen,
        }
        with self._mock_evidence_resolver(ref, tmp_path):
            errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("duplicate path binding" in error for error in errors),
            errors,
        )

    def test_global_closure_missing_path_binding_is_refused(self):
        # F1: dropping any required path binding is refused.
        frozen, tmp_path = self._create_global_closure_receipt("phase1.contract-state-freeze")
        frozen["contracts_schemas"] = frozen["contracts_schemas"][1:]  # drop first
        ref = "operator-os/evidence/GLOBAL-FREEZE-RECEIPT.json"
        ledger = deepcopy(self.ledger)
        ledger["global_blockers"][1]["closure"] = {
            "owner": "ryan",
            "outcome": "implemented",
            "evidence_ref": ref,
            "frozen_boundaries": frozen,
        }
        with self._mock_evidence_resolver(ref, tmp_path):
            errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("missing required path(s)" in error for error in errors),
            errors,
        )

    def test_contract_freeze_closure_unblocks_b1(self):
        # F1 positive control: closing phase1.contract-state-freeze with an exact,
        # exhaustive surface set and governed receipt makes B1 actionable.
        frozen, tmp_path = self._create_global_closure_receipt("phase1.contract-state-freeze", owner="ryan")
        ref = "operator-os/evidence/GLOBAL-FREEZE-RECEIPT.json"
        ledger = deepcopy(self.ledger)
        ledger["global_blockers"][1]["closure"] = {
            "owner": "ryan",
            "outcome": "implemented",
            "evidence_ref": ref,
            "frozen_boundaries": frozen,
        }
        with self._mock_evidence_resolver(ref, tmp_path):
            errors = validate_release_ledger(ledger, self.program, self.suites)
            self.assertEqual(errors, [], errors)
            state = resolve_release_state(ledger, self.program, self.suites)
        actionable_ids = {b["id"] for b in state["actionable_blockers"]}
        self.assertIn("brand-publishing.v1.b1-runtime", actionable_ids)

    def test_retired_suite_requires_owner(self):
        # F2 regression: retired suite without an owner is refused.
        ledger = deepcopy(self.ledger)
        ledger["suites"]["accessibility"]["release_phase"] = "retired"
        ledger["suites"]["accessibility"]["release_phase_owner"] = None
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("retired phase requires a release_phase_owner" in error for error in errors),
            errors,
        )

    def test_deprecated_suite_requires_owner(self):
        # F2 regression: deprecated suite without an owner is refused.
        ledger = deepcopy(self.ledger)
        ledger["suites"]["accessibility"]["release_phase"] = "deprecated"
        ledger["suites"]["accessibility"]["release_phase_owner"] = None
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("deprecated phase requires a release_phase_owner" in error for error in errors),
            errors,
        )

    def test_recovery_depth_validated_for_every_suite_lifecycle(self):
        # F2 regression: recovery depth must be validated for alpha, deprecated, and retired.
        for phase in ("alpha", "deprecated", "retired"):
            ledger = deepcopy(self.ledger)
            ledger["suites"]["accessibility"]["release_phase"] = phase
            ledger["suites"]["accessibility"]["release_phase_owner"] = "ryan"
            ledger["suites"]["accessibility"]["recovery_depth"] = "not-a-real-depth"
            errors = validate_release_ledger(ledger, self.program, self.suites)
            self.assertTrue(
                any("invalid recovery_depth 'not-a-real-depth'" in error for error in errors),
                f"phase={phase}: {errors}",
            )

    def test_retired_suite_requires_governed_retirement_record(self):
        # F2 regression: retired suite requires governed retirement disposition record.
        ledger = deepcopy(self.ledger)
        ledger["suites"]["accessibility"]["release_phase"] = "retired"
        ledger["suites"]["accessibility"]["release_phase_owner"] = "ryan"
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("retired phase requires a governed retirement disposition record" in error for error in errors),
            errors,
        )

    def _create_genuine_retirement_approval(
        self,
        suite_id: str = "accessibility",
        owner: str = "ryan",
        disposition: str = "accessibility donor retired with parity evidence",
        supporting: list[str] | None = None,
    ) -> tuple[dict[str, Any], Path]:
        import datetime
        from portfolio_suites.approvals import (
            APPROVAL_SCHEMA,
            STORE_ENV,
            canonical_digest,
            token_sha256,
            verify_operator_approval,
        )

        if supporting is None:
            supporting = ["accessibility/evidence/A1-WCAG-AUDITOR-PARITY.json"]
        donor = suite_id
        decision = "retire"
        payload = {
            "suite_id": suite_id,
            "donor": donor,
            "decision": decision,
            "disposition": disposition,
            "supporting_evidence_refs": sorted(supporting),
        }
        payload_digest = canonical_digest(payload)
        approval_id = "app-retire-001"
        secret = "secret-12345"
        token = f"opa1.{approval_id}.{secret}"
        now = datetime.datetime.now(datetime.timezone.utc)
        issued_at = (now - datetime.timedelta(hours=1)).isoformat()
        expires_at = (now + datetime.timedelta(hours=5)).isoformat()

        store_dir = tempfile.TemporaryDirectory()
        self.addCleanup(store_dir.cleanup)
        store_path = Path(store_dir.name) / "operator-approvals.json"
        initial_store = {
            "approvals": [
                {
                    "approval_id": approval_id,
                    "schema": APPROVAL_SCHEMA,
                    "token_sha256": token_sha256(token),
                    "operation": "suite-retirement",
                    "decision": decision,
                    "reviewer": owner,
                    "payload_sha256": payload_digest,
                    "suite_id": suite_id,
                    "donor": donor,
                    "issued_at": issued_at,
                    "expires_at": expires_at,
                }
            ]
        }
        store_path.write_text(json.dumps(initial_store, indent=2), encoding="utf-8")

        bindings = {
            "suite_id": suite_id,
            "donor": donor,
            "decision": decision,
            "operation": "suite-retirement",
            "reviewer": owner,
            "payload_sha256": payload_digest,
        }
        with mock.patch.dict("os.environ", {STORE_ENV: str(store_path)}):
            consumed_record = verify_operator_approval(token, bindings)

        receipt = {
            "receipt_version": "portfolio-suite-retirement-v1",
            "suite_id": suite_id,
            "donor": donor,
            "owner": owner,
            "decision": decision,
            "disposition": disposition,
            "supporting_evidence_refs": supporting,
            "approval": consumed_record,
        }
        return receipt, store_path

    def test_retired_suite_rejects_unrelated_parity_receipt(self):
        # F3 regression: an unrelated parity receipt must not be accepted as retirement authorization.
        ledger = deepcopy(self.ledger)
        ledger["suites"]["accessibility"]["release_phase"] = "retired"
        ledger["suites"]["accessibility"]["release_phase_owner"] = "ryan"
        ledger["suites"]["accessibility"]["retirement"] = {
            "owner": "ryan",
            "evidence_ref": "accessibility/evidence/A1-WCAG-AUDITOR-PARITY.json",
            "disposition": "accessibility donor retired with parity evidence",
        }
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("retirement evidence receipt_version must equal 'portfolio-suite-retirement-v1'" in error for error in errors),
            errors,
        )

    def test_retired_suite_rejects_self_authored_receipt_without_approval(self):
        # F3 regression: a self-authored receipt without verified operator approval authority is refused.
        import tempfile
        receipt = {
            "receipt_version": "portfolio-suite-retirement-v1",
            "suite_id": "accessibility",
            "owner": "ryan",
            "decision": "retire",
            "approved_at": "not-a-timestamp",
            "disposition": "retired without authority",
        }
        tmp = tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False)
        json.dump(receipt, tmp)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink, missing_ok=True)

        ref = "accessibility/evidence/A-SELF-AUTHORED.json"
        ledger = deepcopy(self.ledger)
        ledger["suites"]["accessibility"]["release_phase"] = "retired"
        ledger["suites"]["accessibility"]["release_phase_owner"] = "ryan"
        ledger["suites"]["accessibility"]["retirement"] = {
            "owner": "ryan",
            "evidence_ref": ref,
            "disposition": "accessibility donor retired with parity evidence",
        }
        with self._mock_evidence_resolver(ref, Path(tmp.name), expected_suite_id="accessibility"):
            errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("retirement evidence requires a verified operator 'approval' record" in e for e in errors),
            errors,
        )
        self.assertTrue(
            any("disposition does not match ledger retirement disposition" in e for e in errors),
            errors,
        )

    def test_retired_suite_rejects_impossible_timestamp_chronology(self):
        # F1 regression: impossible timestamp chronology must be rejected.
        import tempfile
        receipt, store_path = self._create_genuine_retirement_approval()
        receipt["approval"]["issued_at"] = "2030-01-01T00:00:00+00:00"
        receipt["approval"]["expires_at"] = "2020-01-01T00:00:00+00:00"
        receipt["approval"]["consumed_at"] = "2010-01-01T00:00:00+00:00"

        tmp = tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False)
        json.dump(receipt, tmp)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink, missing_ok=True)

        ref = "accessibility/evidence/A-CHRONOLOGY.json"
        ledger = deepcopy(self.ledger)
        ledger["suites"]["accessibility"]["release_phase"] = "retired"
        ledger["suites"]["accessibility"]["release_phase_owner"] = "ryan"
        ledger["suites"]["accessibility"]["retirement"] = {
            "owner": "ryan",
            "evidence_ref": ref,
            "disposition": receipt["disposition"],
        }
        with mock.patch.dict("os.environ", {"PORTFOLIO_OPERATOR_APPROVAL_STORE": str(store_path)}):
            with self._mock_evidence_resolver(ref, Path(tmp.name), expected_suite_id="accessibility"):
                errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("retirement approval expires at or before it was issued" in e for e in errors),
            errors,
        )
        self.assertTrue(
            any("retirement approval was consumed before it was issued" in e for e in errors),
            errors,
        )

    def test_retired_suite_receipt_mismatches_are_refused(self):
        # F3: receipt must match suite_id, owner, approval reviewer, and payload binding.
        import tempfile
        base_receipt, store_path = self._create_genuine_retirement_approval()

        # 1. suite_id mismatch
        r1 = deepcopy(base_receipt)
        r1["suite_id"] = "brand-publishing"
        tmp1 = tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False)
        json.dump(r1, tmp1)
        tmp1.close()
        self.addCleanup(Path(tmp1.name).unlink, missing_ok=True)

        ledger = deepcopy(self.ledger)
        ledger["suites"]["accessibility"]["release_phase"] = "retired"
        ledger["suites"]["accessibility"]["release_phase_owner"] = "ryan"
        ledger["suites"]["accessibility"]["retirement"] = {
            "owner": "ryan",
            "evidence_ref": "accessibility/evidence/A-RET.json",
            "disposition": base_receipt["disposition"],
        }
        with mock.patch.dict("os.environ", {"PORTFOLIO_OPERATOR_APPROVAL_STORE": str(store_path)}):
            with self._mock_evidence_resolver("accessibility/evidence/A-RET.json", Path(tmp1.name), expected_suite_id="accessibility"):
                errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(any("does not match retired suite 'accessibility'" in e for e in errors), errors)

        # 2. owner mismatch
        r2 = deepcopy(base_receipt)
        r2["owner"] = "wrong-owner"
        tmp2 = tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False)
        json.dump(r2, tmp2)
        tmp2.close()
        self.addCleanup(Path(tmp2.name).unlink, missing_ok=True)
        with mock.patch.dict("os.environ", {"PORTFOLIO_OPERATOR_APPROVAL_STORE": str(store_path)}):
            with self._mock_evidence_resolver("accessibility/evidence/A-RET.json", Path(tmp2.name), expected_suite_id="accessibility"):
                errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(any("does not match release_phase_owner 'ryan'" in e for e in errors), errors)

        # 3. missing token_sha256
        r3 = deepcopy(base_receipt)
        del r3["approval"]["token_sha256"]
        tmp3 = tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False)
        json.dump(r3, tmp3)
        tmp3.close()
        self.addCleanup(Path(tmp3.name).unlink, missing_ok=True)
        with mock.patch.dict("os.environ", {"PORTFOLIO_OPERATOR_APPROVAL_STORE": str(store_path)}):
            with self._mock_evidence_resolver("accessibility/evidence/A-RET.json", Path(tmp3.name), expected_suite_id="accessibility"):
                errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(any("retirement approval requires 'token_sha256'" in e for e in errors), errors)

        # 4. missing consumed_bindings
        r4 = deepcopy(base_receipt)
        del r4["approval"]["consumed_bindings"]
        tmp4 = tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False)
        json.dump(r4, tmp4)
        tmp4.close()
        self.addCleanup(Path(tmp4.name).unlink, missing_ok=True)
        with mock.patch.dict("os.environ", {"PORTFOLIO_OPERATOR_APPROVAL_STORE": str(store_path)}):
            with self._mock_evidence_resolver("accessibility/evidence/A-RET.json", Path(tmp4.name), expected_suite_id="accessibility"):
                errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(any("retirement approval requires 'consumed_bindings'" in e for e in errors), errors)

        # 5. approval reviewer mismatch
        r5 = deepcopy(base_receipt)
        r5["approval"]["reviewer"] = "wrong-reviewer"
        tmp5 = tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False)
        json.dump(r5, tmp5)
        tmp5.close()
        self.addCleanup(Path(tmp5.name).unlink, missing_ok=True)
        with mock.patch.dict("os.environ", {"PORTFOLIO_OPERATOR_APPROVAL_STORE": str(store_path)}):
            with self._mock_evidence_resolver("accessibility/evidence/A-RET.json", Path(tmp5.name), expected_suite_id="accessibility"):
                errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(any("retirement approval reviewer 'wrong-reviewer' does not match" in e for e in errors), errors)

        # 6. approval payload_sha256 mismatch
        r6 = deepcopy(base_receipt)
        r6["approval"]["payload_sha256"] = "0" * 64
        tmp6 = tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False)
        json.dump(r6, tmp6)
        tmp6.close()
        self.addCleanup(Path(tmp6.name).unlink, missing_ok=True)
        with mock.patch.dict("os.environ", {"PORTFOLIO_OPERATOR_APPROVAL_STORE": str(store_path)}):
            with self._mock_evidence_resolver("accessibility/evidence/A-RET.json", Path(tmp6.name), expected_suite_id="accessibility"):
                errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(any("payload_sha256 does not bind exact retirement payload" in e for e in errors), errors)

        # 7. unconsumed approval
        r7 = deepcopy(base_receipt)
        r7["approval"]["consumed"] = False
        tmp7 = tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False)
        json.dump(r7, tmp7)
        tmp7.close()
        self.addCleanup(Path(tmp7.name).unlink, missing_ok=True)
        with mock.patch.dict("os.environ", {"PORTFOLIO_OPERATOR_APPROVAL_STORE": str(store_path)}):
            with self._mock_evidence_resolver("accessibility/evidence/A-RET.json", Path(tmp7.name), expected_suite_id="accessibility"):
                errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(any("retirement approval must be consumed (consumed=True)" in e for e in errors), errors)

        # 8. non-timezone-aware timestamp
        r8 = deepcopy(base_receipt)
        r8["approval"]["consumed_at"] = "2026-08-29T12:00:00"  # missing tzinfo
        tmp8 = tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False)
        json.dump(r8, tmp8)
        tmp8.close()
        self.addCleanup(Path(tmp8.name).unlink, missing_ok=True)
        with mock.patch.dict("os.environ", {"PORTFOLIO_OPERATOR_APPROVAL_STORE": str(store_path)}):
            with self._mock_evidence_resolver("accessibility/evidence/A-RET.json", Path(tmp8.name), expected_suite_id="accessibility"):
                errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(any("must be timezone-aware" in e for e in errors), errors)

    def test_retired_suite_rejects_unverified_authority_store(self):
        # F1: an approval record that cannot be verified against the authority store is refused.
        import tempfile
        receipt, store_path = self._create_genuine_retirement_approval()
        tmp = tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False)
        json.dump(receipt, tmp)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink, missing_ok=True)

        ref = "accessibility/evidence/A-NO-STORE.json"
        ledger = deepcopy(self.ledger)
        ledger["suites"]["accessibility"]["release_phase"] = "retired"
        ledger["suites"]["accessibility"]["release_phase_owner"] = "ryan"
        ledger["suites"]["accessibility"]["retirement"] = {
            "owner": "ryan",
            "evidence_ref": ref,
            "disposition": receipt["disposition"],
        }
        # With no store configured, verify it fails closed
        with mock.patch.dict("os.environ", {}, clear=True):
            with self._mock_evidence_resolver(ref, Path(tmp.name), expected_suite_id="accessibility"):
                errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("retirement approval could not be verified against independent authority" in e for e in errors),
            errors,
        )

    def test_retired_suite_with_governed_record_is_accepted(self):
        # F3 positive control: retired suite with dedicated retirement receipt and verified approval is valid.
        import tempfile
        receipt, store_path = self._create_genuine_retirement_approval()
        tmp = tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False)
        json.dump(receipt, tmp)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink, missing_ok=True)
        ref = "accessibility/evidence/A-RETIREMENT-APPROVAL.json"
        ledger = deepcopy(self.ledger)
        ledger["suites"]["accessibility"]["release_phase"] = "retired"
        ledger["suites"]["accessibility"]["release_phase_owner"] = "ryan"
        ledger["suites"]["accessibility"]["retirement"] = {
            "owner": "ryan",
            "evidence_ref": ref,
            "disposition": receipt["disposition"],
        }
        with mock.patch.dict("os.environ", {"PORTFOLIO_OPERATOR_APPROVAL_STORE": str(store_path)}):
            with self._mock_evidence_resolver(ref, Path(tmp.name), expected_suite_id="accessibility"):
                errors = validate_release_ledger(ledger, self.program, self.suites)
                self.assertEqual(errors, [], errors)
                state = resolve_release_state(ledger, self.program, self.suites)
                self.assertEqual(state["suites"]["accessibility"]["release_phase"], "retired")

    def test_global_blocker_missing_phase0_ledger_is_refused(self):
        # F2 regression: removing phase0.release-ledger is refused.
        ledger = deepcopy(self.ledger)
        ledger["global_blockers"] = [b for b in ledger["global_blockers"] if b.get("id") != "phase0.release-ledger"]
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("global_blockers missing mandatory gate(s): ['phase0.release-ledger']" in e for e in errors),
            errors,
        )

    def test_global_blocker_missing_phase1_contract_freeze_is_refused(self):
        # F2 regression: removing phase1.contract-state-freeze is refused.
        ledger = deepcopy(self.ledger)
        ledger["global_blockers"] = [b for b in ledger["global_blockers"] if b.get("id") != "phase1.contract-state-freeze"]
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("global_blockers missing mandatory gate(s): ['phase1.contract-state-freeze']" in e for e in errors),
            errors,
        )

    def test_global_blocker_missing_phase1_stable_surface_is_refused(self):
        # F2 regression: removing phase1.stable-surface is refused.
        ledger = deepcopy(self.ledger)
        ledger["global_blockers"] = [b for b in ledger["global_blockers"] if b.get("id") != "phase1.stable-surface"]
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("global_blockers missing mandatory gate(s): ['phase1.stable-surface']" in e for e in errors),
            errors,
        )

    def test_global_blocker_unrecognized_gate_is_refused(self):
        # F2 regression: adding an unrecognized global gate is refused.
        ledger = deepcopy(self.ledger)
        ledger["global_blockers"].append({
            "id": "phase9.custom-gate",
            "phase": "0",
            "name": "unauthorized gate",
            "depends_on": [],
            "closure": None,
        })
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("global_blockers contains unrecognized gate(s): ['phase9.custom-gate']" in e for e in errors),
            errors,
        )

    def test_global_blocker_phase_mismatch_is_refused(self):
        # F2 regression: global blocker with wrong phase is refused.
        ledger = deepcopy(self.ledger)
        ledger["global_blockers"][0]["phase"] = "1"
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("phase '1' does not match governed expected phase '0'" in e for e in errors),
            errors,
        )

    def test_validator_totality_over_unhashable_and_malformed_types(self):
        # F3 regression: unhashable types ([], {}) must not raise TypeError.
        for bad_val in ([], {}, 123, True):
            # 1. release_phase
            ledger = deepcopy(self.ledger)
            ledger["suites"]["accessibility"]["release_phase"] = bad_val
            errors = validate_release_ledger(ledger, self.program, self.suites)
            self.assertTrue(any("invalid release_phase" in error for error in errors), f"bad_val={bad_val!r}: {errors}")

            # 2. recovery_depth
            ledger = deepcopy(self.ledger)
            ledger["suites"]["accessibility"]["recovery_depth"] = bad_val
            errors = validate_release_ledger(ledger, self.program, self.suites)
            self.assertTrue(any("invalid recovery_depth" in error for error in errors), f"bad_val={bad_val!r}: {errors}")

            # 3. criterion status
            ledger = deepcopy(self.ledger)
            ledger["suites"]["accessibility"]["criteria"][0]["status"] = bad_val
            errors = validate_release_ledger(ledger, self.program, self.suites)
            self.assertTrue(any("invalid status" in error for error in errors), f"bad_val={bad_val!r}: {errors}")

            # 4. release blocker phase
            ledger = deepcopy(self.ledger)
            ledger["release_blockers"][0]["phase"] = bad_val
            errors = validate_release_ledger(ledger, self.program, self.suites)
            self.assertTrue(any("invalid phase" in error for error in errors), f"bad_val={bad_val!r}: {errors}")

            # 5. global blocker phase
            ledger = deepcopy(self.ledger)
            ledger["global_blockers"][0]["phase"] = bad_val
            errors = validate_release_ledger(ledger, self.program, self.suites)
            self.assertTrue(any("invalid phase" in error for error in errors), f"bad_val={bad_val!r}: {errors}")

    def test_first_criterion_closed_with_empty_refs_does_not_raise_unbound_local(self):
        # F3 regression: closed first criterion with empty obligation_refs and closure
        # must report validation errors rather than raising UnboundLocalError.
        ledger = deepcopy(self.ledger)
        crit = ledger["suites"]["accessibility"]["criteria"][0]
        crit["status"] = "closed"
        crit["obligation_refs"] = []
        crit["closure"] = {
            "outcome": "implemented",
            "owner": "ryan",
            "evidence_ref": "accessibility/evidence/A2-ADOPTION.json",
        }
        errors = validate_release_ledger(ledger, self.program, self.suites)
        self.assertTrue(
            any("obligation_refs must be a non-empty list" in error for error in errors),
            errors,
        )

    def test_resolve_criterion_state_preserves_obligation_identity_in_residual(self):
        # F4: residual_obligations must contain dicts with obligation id and state.
        from portfolio_suites.release_state import _resolve_criterion_state
        criterion = {
            "id": "accessibility.v1.runtime-parity",
            "status": "open",
            "obligation_refs": [
                {"id": "accessibility/A1"},
                {"id": "accessibility/A3"},
                {"id": "accessibility/A4"},
            ],
        }
        effective = {
            "accessibility/A1": "ready",
            "accessibility/A3": "blocked_dependency",
            "accessibility/A4": "discharged",
        }
        result = _resolve_criterion_state(criterion, effective)
        self.assertEqual(result["status"], "open")
        self.assertEqual(
            result["residual_obligations"],
            [
                {"id": "accessibility/A1", "state": "ready"},
                {"id": "accessibility/A3", "state": "blocked_dependency"},
            ],
        )
        self.assertEqual(result["residual_obligation_ids"], ["accessibility/A1", "accessibility/A3"])
        self.assertEqual(
            result["obligation_states_by_id"],
            {
                "accessibility/A1": "ready",
                "accessibility/A3": "blocked_dependency",
                "accessibility/A4": "discharged",
            },
        )


class ReleaseLedgerIntegrationTests(unittest.TestCase):
    """The release ledger is a first-class validation artifact, so `suites validate`
    must fail when it is malformed, not silently ignore it."""

    def test_registry_validation_rejects_malformed_release_ledger(self):
        from portfolio_suites import release_state
        from portfolio_suites.registry import validate_registry

        malformed = (
            '{"ledger_id": "portfolio-release-completion-v1", "schema_version": "1.0.0",'
            ' "suites": {}}'
        )
        with TemporaryDirectory() as tmp:
            tmp_ledger = Path(tmp) / "release-ledger.json"
            tmp_ledger.write_text(malformed, encoding="utf-8")
            # Redirect the ledger read to a throwaway copy so the real tracked
            # artifact is never touched, even if this test is interrupted.
            with mock.patch.object(release_state, "RELEASE_LEDGER_PATH", tmp_ledger):
                report = validate_registry(check_live=False)
        self.assertFalse(report.ok)
        self.assertTrue(
            any("release ledger" in error for error in report.errors),
            report.errors,
        )

    def _ledger_path(self):
        from portfolio_suites.release_state import RELEASE_LEDGER_PATH

        return RELEASE_LEDGER_PATH


if __name__ == "__main__":
    unittest.main()
