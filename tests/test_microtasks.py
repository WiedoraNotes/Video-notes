"""Regression checks for the independent KWN acceptance microtask ledger."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scripts.check_vn_microtasks import ROOT, audit, summary, validate_acceptance_receipt


class MicrotaskAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.queue = json.loads((ROOT / "docs" / "VN_MICROTASKS.json").read_text(encoding="utf-8"))
        cls.phases = json.loads((ROOT / "docs" / "VN_STATUS.json").read_text(encoding="utf-8"))

    def test_real_queue_is_structurally_valid(self):
        self.assertEqual(audit(self.queue, self.phases), [])
        result = summary(self.queue, self.phases)
        self.assertEqual(result["tasks"], len(self.queue["tasks"]))
        self.assertEqual(result["stage_status"], self.phases["totals"])
        self.assertTrue(result["ready_task_ids"])

    def test_duplicate_ids_fail(self):
        queue = copy.deepcopy(self.queue)
        queue["tasks"].append(copy.deepcopy(queue["tasks"][0]))
        queue["totals"]["tasks"] += 1
        self.assertTrue(any("duplicate ID" in x for x in audit(queue, self.phases)))

    def test_unknown_dependency_fails(self):
        queue = copy.deepcopy(self.queue)
        queue["tasks"][0]["depends_on"] = ["VN-99-99"]
        self.assertTrue(any("dependency not found" in x for x in audit(queue, self.phases)))

    def test_dependency_cycle_fails(self):
        queue = copy.deepcopy(self.queue)
        queue["tasks"][0]["depends_on"] = [queue["tasks"][1]["id"]]
        queue["tasks"][1]["depends_on"] = [queue["tasks"][0]["id"]]
        self.assertTrue(any("dependency cycle" in x for x in audit(queue, self.phases)))

    def test_done_without_evidence_is_rejected(self):
        queue = copy.deepcopy(self.queue)
        queue["tasks"][0]["status"] = "DONE"
        # Earlier TODO tasks may legitimately carry preparatory PR evidence.
        # This negative test must remove references regardless of ledger state.
        queue["tasks"][0]["evidence_refs"] = []
        self.assertTrue(any("DONE requires" in x for x in audit(queue, self.phases)))

    def test_done_with_unfinished_prerequisite_is_rejected(self):
        queue = copy.deepcopy(self.queue)
        target = next(t for t in queue["tasks"] if t["depends_on"])
        target["status"] = "DONE"
        target["evidence_refs"] = ["https://github.com/example/repo/pull/1"]
        self.assertTrue(any("prerequisites" in x for x in audit(queue, self.phases)))

    def test_stage_done_cannot_be_inferred_from_ci(self):
        phases = copy.deepcopy(self.phases)
        phases["phases"][0]["status"] = "DONE"
        phases["totals"]["DONE"] += 1
        phases["totals"]["W_TRAKCIE"] -= 1
        self.assertTrue(any("unfinished microtasks" in x for x in audit(self.queue, phases)))

    def test_mismatched_stage_fails(self):
        queue = copy.deepcopy(self.queue)
        queue["tasks"][0]["stage"] = "VN-06"
        self.assertTrue(any("stage mismatch" in x for x in audit(queue, self.phases)))


    def test_human_task_cannot_be_done_using_only_successful_ci_and_pr(self):
        queue = copy.deepcopy(self.queue)
        task = next(t for t in queue["tasks"] if t["id"] == "VN-07-02")
        self.assertEqual(task["owner"], "HUMAN_TEST")
        self.assertEqual(next(t for t in queue["tasks"] if t["id"] == "VN-07-01")["status"], "DONE")
        task["status"] = "DONE"
        task["evidence_refs"] = ["https://github.com/testowyemailaplikacja-spec/Video-notes/pull/219"]
        errors = audit(queue, self.phases)
        self.assertTrue(any("requires independent human acceptance receipt" in e for e in errors))

    def test_acceptance_receipt_requires_scoped_independent_issue_and_nonfuture_date(self):
        task = next(t for t in self.queue["tasks"] if t["id"] == "VN-07-02")
        test_task = copy.deepcopy(task)
        test_task["status"] = "DONE"
        issue = "https://github.com/testowyemailaplikacja-spec/Video-notes/issues/95"
        test_task["evidence_refs"] = [issue]
        test_task["acceptance_receipt"] = {
            "schema": "videonotes-human-acceptance-v1",
            "case_id": "WEB-01", "kind": "PHYSICAL_WINDOWS",
            "decision": "APPROVED", "checked_at": "2026-11-15",
            "verified_commit": "a" * 40, "attested_by_human": True,
            "independently_reviewed": True, "evidence_url": issue,
        }
        # A structurally well-formed record is NOT proof that a human actually
        # executed the test, signed it, or owns the issue; offline audit cannot
        # assert that. This test validates only fail-closed field handling.
        self.assertEqual(validate_acceptance_receipt(test_task), [])
        fake = copy.deepcopy(test_task)
        fake["acceptance_receipt"]["kind"] = "CI"
        self.assertTrue(any("scope" in e for e in validate_acceptance_receipt(fake)))
        fake = copy.deepcopy(test_task)
        fake["acceptance_receipt"]["evidence_url"] = "https://github.com/owner/repo/pull/1"
        self.assertTrue(any("metadata-only" in e for e in validate_acceptance_receipt(fake)))
        fake = copy.deepcopy(test_task)
        fake["acceptance_receipt"]["checked_at"] = "2999-12-31"
        self.assertTrue(any("future" in e for e in validate_acceptance_receipt(fake)))
        fake = copy.deepcopy(test_task)
        fake["acceptance_receipt"]["independently_reviewed"] = False
        self.assertTrue(any("independent" in e for e in validate_acceptance_receipt(fake)))

    def test_portal_task_needs_verified_deploy_and_host_regression(self):
        task = copy.deepcopy(next(t for t in self.queue["tasks"] if t["id"] == "VN-07-05"))
        url = "https://github.com/testowyemailaplikacja-spec/Constant_app/issues/95"
        task["evidence_refs"] = [url]
        task["acceptance_receipt"] = {
            "schema": "videonotes-human-acceptance-v1",
            "case_id": "HOST-01", "kind": "PORTAL_REVIEW",
            "decision": "APPROVED", "checked_at": "2026-11-15",
            "verified_commit": "a" * 40,
            "attested_by_human": True, "independently_reviewed": True,
            "evidence_url": url,
            "deployed_sha": "", "environment_verified": False,
            "full_regression_url": "",
        }
        errors = validate_acceptance_receipt(task)
        self.assertTrue(any("deployed SHA" in e for e in errors))
        self.assertTrue(any("full-regression" in e for e in errors))
        task["acceptance_receipt"]["deployed_sha"] = "b" * 40
        task["acceptance_receipt"]["environment_verified"] = True
        task["acceptance_receipt"]["full_regression_url"] = (
            "https://github.com/testowyemailaplikacja-spec/Constant_app/actions/runs/43672684828"
        )
        # Structural format alone cannot tell that the linked workflow failed.
        # Full CI status and environment SHA must be checked independently.
        self.assertEqual(validate_acceptance_receipt(task), [])



if __name__ == "__main__":
    unittest.main()
