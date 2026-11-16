"""Read-only integrity checks for the KWN microtask queue.

This ledger plans work; it is NOT proof of physical or human acceptance.
No automatic updates to docs/VN_STATUS.json or user data.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


# Additional structural gate only; true provenance, physical execution and
# independent human authorization must still be verified outside this script.
REVIEW_KIND = {
    "HUMAN_TEST": "PHYSICAL_WINDOWS",
    "REVIEW": "HUMAN_REVIEW",
    "LEGAL": "LEGAL_REVIEW",
    "PORTAL": "PORTAL_REVIEW",
    "DECISION": "PRODUCT_DECISION",
}
RECEIPT_KEYS = {
    "schema", "case_id", "kind", "decision", "checked_at", "verified_commit",
    "attested_by_human", "independently_reviewed", "evidence_url",
}

SOURCE_REPOS = ("WiedoraNotes/Video-notes", "testowyemailaplikacja-spec/Video-notes")
PORTAL_REPOS = ("wiedoraWeb/Constant_app", "testowyemailaplikacja-spec/Constant_app")


def _scoped_metadata_url(value: object, repos: tuple[str, ...], path: str) -> bool:
    """Validate exact repository and resource type; legacy evidence remains readable."""
    return isinstance(value, str) and any(
        re.fullmatch(r"https://github[.]com/" + re.escape(repo) + path, value) is not None
        for repo in repos
    )


def validate_acceptance_receipt(task: dict) -> list[str]:
    """Require a reviewable, scoped receipt before any non-DEV microtask is DONE.

    It checks only data shape, never the truth of a human attestation or
    authenticity of an external GitHub issue. An API review is still required.
    """
    uid = task["id"]
    expected_kind = REVIEW_KIND.get(task.get("owner"))
    if not expected_kind:
        return []
    receipt = task.get("acceptance_receipt")
    if not isinstance(receipt, dict):
        return [f"{uid}: non-DEV DONE requires independent human acceptance receipt"]
    required = RECEIPT_KEYS | ({"deployed_sha", "full_regression_url", "environment_verified"}
                                if expected_kind == "PORTAL_REVIEW" else set())
    if set(receipt) != required:
        return [f"{uid}: acceptance receipt has missing or unexpected fields"]
    errors = []
    if (receipt.get("schema") != "videonotes-human-acceptance-v1"
            or receipt.get("case_id") != task.get("acceptance_id")
            or receipt.get("kind") != expected_kind
            or receipt.get("decision") != "APPROVED"):
        errors.append(f"{uid}: acceptance receipt type/scope/decision mismatch")
    if receipt.get("attested_by_human") is not True or receipt.get("independently_reviewed") is not True:
        errors.append(f"{uid}: no independent human review attestation")
    if not isinstance(receipt.get("verified_commit"), str) or not re.fullmatch(
            r"[0-9a-f]{40}", receipt["verified_commit"]):
        errors.append(f"{uid}: invalid tested Git commit")
    checked_at = receipt.get("checked_at")
    try:
        from datetime import date
        if not isinstance(checked_at, str) or date.fromisoformat(checked_at).isoformat() != checked_at:
            raise ValueError("bad date")
        if date.fromisoformat(checked_at) > date.today():
            raise ValueError("future review")
    except ValueError:
        errors.append(f"{uid}: invalid or future acceptance date")
    url = receipt.get("evidence_url")
    issue_repos = PORTAL_REPOS if expected_kind == "PORTAL_REVIEW" else SOURCE_REPOS
    references = task.get("evidence_refs")
    if (not _scoped_metadata_url(url, issue_repos, r"/issues/[1-9][0-9]*")
            or not isinstance(references, list) or url not in references):
        errors.append(f"{uid}: receipt needs registered metadata-only GitHub issue")
    if expected_kind == "PORTAL_REVIEW":
        deployed = receipt.get("deployed_sha")
        run_url = receipt.get("full_regression_url")
        if (not isinstance(deployed, str) or not re.fullmatch(r"[0-9a-f]{40}", deployed)
                or receipt.get("environment_verified") is not True):
            errors.append(f"{uid}: portal receipt requires verified deployed SHA")
        if not _scoped_metadata_url(run_url, PORTAL_REPOS, r"/actions/runs/[1-9][0-9]*"):
            errors.append(f"{uid}: portal receipt needs a reviewable full-regression run")
    return errors


ROOT = Path(__file__).resolve().parents[1]
TASK_FILE = ROOT / "docs" / "VN_MICROTASKS.json"
STATUS_FILE = ROOT / "docs" / "VN_STATUS.json"
ID_RE = re.compile(r"VN-0[0-8]-[0-9]{2}\Z")


def audit(queue: dict, stage_ledger: dict) -> list[str]:
    """Return deterministic validation errors, without mutating either input."""
    errors: list[str] = []
    tasks = queue.get("tasks")
    phases = stage_ledger.get("phases")
    if not isinstance(tasks, list) or not isinstance(phases, list):
        return ["Missing tasks or stage phases list"]
    if queue.get("repository") != SOURCE_REPOS[0]:
        errors.append("Microtask ledger repository mismatch")
    if stage_ledger.get("owner_repo") != SOURCE_REPOS[0]:
        errors.append("Stage ledger repository mismatch")
    expected = {f"VN-{index:02d}" for index in range(9)}
    registered = {p.get("id") for p in phases if isinstance(p, dict)}
    if registered != expected:
        errors.append("Stage ledger does not contain exactly VN-00..VN-08")
    valid_status = {"TODO", "IN_PROGRESS", "BLOCKED", "DONE"}
    valid_stage_status = {"W_TRAKCIE", "PLANOWANE", "DONE"}
    owners = {"DEV", "HUMAN_TEST", "REVIEW", "LEGAL", "PORTAL", "DECISION"}
    priorities = {"P0", "P1", "P2"}
    by_id: dict[str, dict] = {}
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            errors.append(f"tasks[{index}]: not an object")
            continue
        uid = task.get("id")
        if not isinstance(uid, str) or not ID_RE.fullmatch(uid):
            errors.append(f"tasks[{index}]: invalid ID")
            continue
        if uid in by_id:
            errors.append(f"{uid}: duplicate ID")
        by_id[uid] = task
        if task.get("stage") != uid[:5] or task.get("stage") not in expected:
            errors.append(f"{uid}: stage mismatch")
        if task.get("status") not in valid_status:
            errors.append(f"{uid}: invalid status")
        if task.get("priority") not in priorities:
            errors.append(f"{uid}: invalid priority")
        if task.get("owner") not in owners:
            errors.append(f"{uid}: invalid owner")
        if not isinstance(task.get("title"), str) or not task["title"].strip():
            errors.append(f"{uid}: missing title")
        if not isinstance(task.get("acceptance_id"), str) or not re.fullmatch(
            r"(?:HW|ASR|NOTE|MIC|MIX|WEB|PKG|HOST|MOB)-[0-9]{2}",
            task["acceptance_id"],
        ):
            errors.append(f"{uid}: unknown acceptance ID format")
        if not isinstance(task.get("depends_on"), list):
            errors.append(f"{uid}: dependencies must be a list")
        if task.get("status") == "DONE":
            evidence = task.get("evidence_refs")
            if not isinstance(evidence, list) or not evidence or not all(
                isinstance(v, str) and v.startswith("https://github.com/") for v in evidence
            ):
                errors.append(f"{uid}: DONE requires reviewable GitHub evidence references")
            errors.extend(validate_acceptance_receipt(task))
    for uid, task in by_id.items():
        deps = task.get("depends_on")
        if not isinstance(deps, list):
            continue
        if len(deps) != len(set(map(str, deps))):
            errors.append(f"{uid}: duplicate dependencies")
        for dep in deps:
            if not isinstance(dep, str) or dep not in by_id:
                errors.append(f"{uid}: dependency not found")
            elif dep == uid:
                errors.append(f"{uid}: self dependency")
        if task.get("status") == "DONE" and any(
            by_id.get(dep, {}).get("status") != "DONE" for dep in deps if isinstance(dep, str)
        ):
            errors.append(f"{uid}: DONE while prerequisites are not DONE")
    colors: dict[str, int] = {}
    def visit(uid: str) -> None:
        if colors.get(uid) == 2:
            return
        if colors.get(uid) == 1:
            errors.append(f"{uid}: dependency cycle")
            return
        colors[uid] = 1
        for dep in by_id[uid].get("depends_on", []):
            if isinstance(dep, str) and dep in by_id:
                visit(dep)
        colors[uid] = 2
    for uid in sorted(by_id):
        visit(uid)
    if queue.get("totals", {}).get("tasks") != len(tasks):
        errors.append("Task total does not match list length")
    if queue.get("totals", {}).get("stages") != len(expected):
        errors.append("Stage total must be nine")
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        stage, state = phase.get("id"), phase.get("status")
        if state not in valid_stage_status:
            errors.append(f"{stage}: invalid phase status")
        if state == "DONE" and any(
            task.get("status") != "DONE" for task in by_id.values() if task.get("stage") == stage
        ):
            errors.append(f"{stage}: stage marked DONE with unfinished microtasks")
    reported_totals = stage_ledger.get("totals", {})
    actual = Counter(p.get("status") for p in phases if isinstance(p, dict))
    if any(reported_totals.get(key) != actual[key] for key in valid_stage_status):
        errors.append("Stage summary totals do not match phase statuses")
    return sorted(set(errors))


def summary(queue: dict, stage_ledger: dict) -> dict:
    tasks = queue["tasks"]
    done = {t["id"] for t in tasks if t["status"] == "DONE"}
    ready = [t["id"] for t in tasks if t["status"] == "TODO"
             and all(dep in done for dep in t["depends_on"])]
    ready.sort(key=lambda uid: (next(t["priority"] for t in tasks if t["id"] == uid), uid))
    return {
        "schema": "videonotes-microtasks-audit-v1",
        "tasks": len(tasks),
        "task_states": dict(sorted(Counter(t["status"] for t in tasks).items())),
        "ready_task_ids": ready,
        "stages_source": "docs/VN_STATUS.json",
        "stage_status": stage_ledger["totals"],
        "warning": "This output is a work queue, not evidence of acceptance.",
    }



def handoff(queue: dict, stage_ledger: dict) -> dict:
    """Generate a conservative, metadata-only handoff from validated ledgers.

    No remote checks, filesystem writes, external permissions or unearned DONE.
    Only PORTAL is a strictly Work-relevant owner category; physical hardware,
    editorial/legal review and product decisions stay with the operator.
    """
    if audit(queue, stage_ledger):
        raise ValueError("Cannot create a handoff from inconsistent ledgers")
    done = {t["id"] for t in queue["tasks"] if t["status"] == "DONE"}
    remaining = []
    owner_actions = {
        "DEV": "Complete missing coding, tests and any specified real inference gate",
        "HUMAN_TEST": "Perform and independently attest real physical/device tests",
        "REVIEW": "Independently review actual source material and factual accuracy",
        "LEGAL": "Obtain real legal/license review and distribution authorization",
        "DECISION": "Obtain explicit owner product-scope decision",
        "PORTAL": "Verify real Wiedora staging deployment, GUI and full host regression",
    }
    for task in queue["tasks"]:
        if task["status"] == "DONE":
            continue
        unmet = [dep for dep in task["depends_on"] if dep not in done]
        refs = task.get("evidence_refs", [])
        remaining.append({
            "id": task["id"], "stage": task["stage"],
            "owner": task["owner"], "priority": task["priority"],
            "status": task["status"], "task_scope": task["title"],
            "acceptance_id": task["acceptance_id"],
            "unmet_dependencies": unmet,
            "dependency_ready": not unmet and task["status"] != "BLOCKED",
            "required_external_action": owner_actions[task["owner"]],
            "prior_evidence_urls": [
                ref for ref in refs
                if isinstance(ref, str) and ref.startswith("https://github.com/")
            ] if isinstance(refs, list) else [],
            "verified_implementation_sha": None,
            "requires_independent_evidence_review": True,
        })
    work = [item for item in remaining if item["owner"] == "PORTAL"]
    other = [item for item in remaining if item["owner"] != "PORTAL"]
    return {
        "schema": "videonotes-operator-handoff-v1",
        "repository": queue["repository"],
        "ledger_sources": ["docs/VN_MICROTASKS.json", "docs/VN_STATUS.json"],
        "stages": stage_ledger["totals"],
        "remaining_count": len(remaining),
        "counts_by_owner": dict(sorted(Counter(item["owner"] for item in remaining).items())),
        "work": {
            "count": len(work),
            "dependency_ready_count": sum(item["dependency_ready"] for item in work),
            "tasks": work,
        },
        "non_work": {"count": len(other), "tasks": other},
        "work_assist_only": ["VN-07-03"] if any(
            item["id"] == "VN-07-03" for item in other
        ) else [],
        "notes": [
            "Dependency-ready is not a verified environment, hardware or acceptance PASS.",
            "Work-assist-only tasks still need independent operator/human acceptance.",
            "Evidence links and implementation SHA must be checked against actual GitHub and deployed code.",
            "No task status is changed; this output does not authorize paid operations.",
        ],
        "verified_commit_sha": None,
        "formal_acceptance_completed_by_this_report": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only KWN microtask plan integrity check")
    parser.add_argument("--queue", type=Path, default=TASK_FILE)
    parser.add_argument("--stages", type=Path, default=STATUS_FILE)
    parser.add_argument(
        "--handoff", action="store_true",
        help="Show dependency-scoped Work/operator handoff without changing ledgers",
    )
    args = parser.parse_args()
    queue = json.loads(args.queue.read_text(encoding="utf-8"))
    stage_ledger = json.loads(args.stages.read_text(encoding="utf-8"))
    errors = audit(queue, stage_ledger)
    if errors:
        print(json.dumps({"valid": False, "errors": errors}, indent=2))
        return 1
    result = handoff(queue, stage_ledger) if args.handoff else summary(queue, stage_ledger)
    print(json.dumps({"valid": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
