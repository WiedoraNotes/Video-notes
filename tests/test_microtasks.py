"""Regression checks for the independent KWN acceptance microtask ledger."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from scripts.check_vn_microtasks import ROOT, audit, handoff, summary, validate_acceptance_receipt


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


    def test_ledger_must_reference_new_repo(self):
        queue = copy.deepcopy(self.queue)
        queue["repository"] = "testowyemailaplikacja-spec/Video-notes"
        self.assertTrue(any("Microtask ledger repository mismatch" in e for e in audit(queue, self.phases)))
        phases = copy.deepcopy(self.phases)
        phases["owner_repo"] = "testowyemailaplikacja-spec/Video-notes"
        self.assertTrue(any("Stage ledger repository mismatch" in e for e in audit(self.queue, phases)))

    def test_current_and_historical_receipts_require_proper_repo(self):
        task = copy.deepcopy(next(t for t in self.queue["tasks"] if t["id"] == "VN-07-02"))
        current = "https://github.com/WiedoraNotes/Video-notes/issues/95"
        legacy = "https://github.com/testowyemailaplikacja-spec/Video-notes/issues/95"
        task["evidence_refs"] = [current, legacy]
        task["acceptance_receipt"] = {
            "schema": "videonotes-human-acceptance-v1", "case_id": "WEB-01",
            "kind": "PHYSICAL_WINDOWS", "decision": "APPROVED",
            "checked_at": "2026-11-15", "verified_commit": "a" * 40,
            "attested_by_human": True, "independently_reviewed": True,
            "evidence_url": current,
        }
        self.assertEqual(validate_acceptance_receipt(task), [])
        task["acceptance_receipt"]["evidence_url"] = legacy
        self.assertEqual(validate_acceptance_receipt(task), [])
        task["acceptance_receipt"]["evidence_url"] = "https://github.com/wiedoraWeb/Constant_app/issues/95"
        self.assertTrue(validate_acceptance_receipt(task))
        task["acceptance_receipt"]["evidence_url"] = "https://github.com/WiedoraNotes/Video-notes/pull/95"
        self.assertTrue(validate_acceptance_receipt(task))

    def test_portal_receipt_requires_portal_issue_and_full_regression(self):
        task = copy.deepcopy(next(t for t in self.queue["tasks"] if t["id"] == "VN-07-05"))
        issue = "https://github.com/wiedoraWeb/Constant_app/issues/95"
        task["evidence_refs"] = [issue]
        task["acceptance_receipt"] = {
            "schema": "videonotes-human-acceptance-v1", "case_id": "HOST-01",
            "kind": "PORTAL_REVIEW", "decision": "APPROVED",
            "checked_at": "2026-11-15", "verified_commit": "a" * 40,
            "attested_by_human": True, "independently_reviewed": True,
            "evidence_url": issue, "deployed_sha": "b" * 40,
            "environment_verified": True,
            "full_regression_url": "https://github.com/wiedoraWeb/Constant_app/actions/runs/95",
        }
        self.assertEqual(validate_acceptance_receipt(task), [])
        task["acceptance_receipt"]["full_regression_url"] = "https://github.com/WiedoraNotes/Video-notes/actions/runs/95"
        self.assertTrue(any("full-regression" in e for e in validate_acceptance_receipt(task)))

    def test_handoff_sends_only_portal_to_strict_work_and_preserves_all_statuses(self):
        queue = copy.deepcopy(self.queue)
        before = json.dumps(queue, sort_keys=True)
        report = handoff(queue, self.phases)
        self.assertEqual(report["remaining_count"], 35)
        self.assertEqual(report["work"]["count"], 1)
        self.assertEqual(report["work"]["dependency_ready_count"], 0)
        self.assertEqual(report["non_work"]["count"], 34)
        self.assertEqual(report["counts_by_owner"]["HUMAN_TEST"], 24)
        self.assertEqual(report["counts_by_owner"]["DEV"], 2)
        self.assertEqual(report["work"]["tasks"][0]["id"], "VN-07-05")
        self.assertEqual(report["work"]["tasks"][0]["unmet_dependencies"],
                         ["VN-07-03", "VN-06-04"])
        self.assertIn("VN-07-03", report["work_assist_only"])
        self.assertIsNone(report["verified_commit_sha"])
        self.assertFalse(report["formal_acceptance_completed_by_this_report"])
        self.assertEqual(json.dumps(queue, sort_keys=True), before)

    def test_handoff_dependency_ready_is_not_formal_approval(self):
        report = handoff(self.queue, self.phases)
        step = next(x for x in report["non_work"]["tasks"] if x["id"] == "VN-07-02")
        self.assertTrue(step["dependency_ready"])
        self.assertTrue(step["requires_independent_evidence_review"])
        self.assertIsNone(step["verified_implementation_sha"])
        self.assertNotIn("VN-07-01", [x["id"] for x in report["non_work"]["tasks"]])
        queue = copy.deepcopy(self.queue)
        queue["repository"] = "testowyemailaplikacja-spec/Video-notes"
        with self.assertRaises(ValueError):
            handoff(queue, self.phases)

    def test_handoff_cli_is_read_only_and_valid_json(self):
        import subprocess
        import sys
        response = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "check_vn_microtasks.py"), "--handoff"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            timeout=15, cwd=ROOT, text=True,
        )
        self.assertEqual(response.returncode, 0, response.stderr)
        data = json.loads(response.stdout)
        self.assertTrue(data["valid"])
        self.assertEqual(data["schema"], "videonotes-operator-handoff-v1")
        self.assertEqual(data["work"]["dependency_ready_count"], 0)


if __name__ == "__main__":
    unittest.main()
