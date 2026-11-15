"""Local Windows browser matrix for VN-07 WEB-01/WEB-02 preflight.

Runs existing synthetic browser scenarios in physical Windows installations.
Never asserts physical or human PASS. No downloads, microphone or real recordings.
JSON evidence contains no local paths, hostnames, usernames or private transcripts.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"^[0-9a-f]{40}$")
SCHEMA = "videonotes-vn07-windows-browser-matrix-v1"
BROWSERS = ("chrome", "edge", "firefox")
MAX_OUTPUT = 16 * 1024


def browser_executable(name: str, supplied: str | None = None) -> str | None:
    """Resolve only existing executables; never install browsers or drivers."""
    if supplied:
        candidate = Path(supplied).expanduser()
        if candidate.is_file() and not candidate.is_symlink():
            return str(candidate.resolve())
        return shutil.which(supplied)
    defaults = {
        "chrome": ("chrome.exe", "chrome", "google-chrome"),
        "edge": ("msedge.exe", "msedge"),
        "firefox": ("firefox.exe", "firefox"),
        "geckodriver": ("geckodriver.exe", "geckodriver"),
        "node": ("node.exe", "node"),
    }
    for binary in defaults[name]:
        located = shutil.which(binary)
        if located:
            return located
    program_files = [os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"),
                     os.environ.get("LOCALAPPDATA")]
    tails = {
        "chrome": ("Google", "Chrome", "Application", "chrome.exe"),
        "edge": ("Microsoft", "Edge", "Application", "msedge.exe"),
        "firefox": ("Mozilla Firefox", "firefox.exe"),
    }
    if name in tails:
        for folder in filter(None, program_files):
            path = Path(folder).joinpath(*tails[name])
            if path.is_file() and not path.is_symlink():
                return str(path)
    return None


def command_runner(command: list[str], extra_env: dict[str, str], timeout: int) -> int:
    """Run synthetic scripts, discarding output to avoid private diagnostic leaks."""
    environment = os.environ.copy()
    environment.update(extra_env)
    completed = subprocess.run(command, cwd=ROOT, env=environment,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=timeout, check=False)
    return completed.returncode


def run_matrix(programs: dict[str, str | None],
               invoke: Callable[[list[str], dict[str, str], int], int] = command_runner) -> dict:
    """A successful script proves automation only, not hardware or NVDA acceptance."""
    results = {}
    for name in BROWSERS:
        missing = []
        if not programs.get("node"):
            missing.append("node")
        if not programs.get(name):
            missing.append(name)
        if name == "firefox" and not programs.get("geckodriver"):
            missing.append("geckodriver")
        if missing:
            results[name] = {"status": "NOT_RUN", "reason": "MISSING_EXECUTABLE"}
            continue
        if name == "firefox":
            command = [programs["node"], str(ROOT / "scripts" / "firefox-smoke.cjs")]
            environment = {"GECKODRIVER_BIN": programs["geckodriver"]}
        else:
            command = [programs["node"], str(ROOT / "scripts" / "browser-smoke.cjs")]
            environment = {"CHROME_BIN": programs[name]}
        try:
            code = invoke(command, environment, 240)
        except subprocess.TimeoutExpired:
            results[name] = {"status": "AUTOMATED_FAIL", "reason": "TIMEOUT"}
        except OSError:
            results[name] = {"status": "NOT_RUN", "reason": "PROCESS_START_FAILED"}
        else:
            results[name] = ({
                "status": "AUTOMATED_PASS", "reason": "SYNTHETIC_BROWSER_SMOKE"
            } if code == 0 else {
                "status": "AUTOMATED_FAIL", "reason": "NONZERO_EXIT"
            })
    return results


def current_checkout(invoke: Callable | None = None) -> tuple[str, str]:
    """Return current branch and immutable commit; never contact the network."""
    if invoke is None:
        def invoke(command: list[str]) -> str:
            return subprocess.check_output(command, cwd=ROOT, stderr=subprocess.DEVNULL,
                                           timeout=8, text=True).strip()
    try:
        sha = invoke(["git", "rev-parse", "HEAD"])
        branch = invoke(["git", "branch", "--show-current"])
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise ValueError("Cannot inspect local Git checkout") from error
    if not SHA.fullmatch(sha) or branch != "develop":
        raise ValueError("Expected cleanly identified develop branch")
    return branch, sha


def publish_report(destination: Path, report: dict) -> None:
    """Exclusive create in an existing real parent; no overwrite or symlink."""
    destination = Path(destination).expanduser().absolute()
    if destination.suffix.lower() != ".json":
        raise ValueError("Expected JSON report target")
    if destination.exists() or destination.is_symlink():
        raise ValueError("Refusing to overwrite existing report")
    parent = destination.parent
    if not parent.is_dir() or any(p.is_symlink() or getattr(p, "is_junction", lambda: False)()
                                 for p in (parent, *parent.parents)):
        raise ValueError("Unsafe report parent")
    payload = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(payload) > MAX_OUTPUT:
        raise ValueError("Unexpected oversized report")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(destination, flags, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if not stat.S_ISREG(destination.lstat().st_mode):
            raise ValueError("Output must be a regular file")
    except FileExistsError as error:
        raise ValueError("Report was concurrently created; no overwrite") from error


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline synthetic browser smoke on real Windows")
    parser.add_argument("--output", type=Path, required=True, help="New local .json report file")
    for name in ("node", "chrome", "edge", "firefox", "geckodriver"):
        parser.add_argument("--" + name, help="Optional existing executable path")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Physical Windows only; never infer Windows acceptance from CI Linux")
    try:
        _branch, sha = current_checkout()
        programs = {name: browser_executable(name, getattr(args, name))
                    for name in ("node", "chrome", "edge", "firefox", "geckodriver")}
        outcomes = run_matrix(programs)
        _after_branch, final_sha = current_checkout()
        if final_sha != sha:
            raise ValueError("Source checkout changed while running browser tests")
        report = {
            "schema": SCHEMA,
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_sha": sha,
            "tests": outcomes,
            "synthetic_only": True,
            "network_independence_not_independently_verified": True,
            "hardware_attested": False,
            "nvda_human_review": "NOT_RUN",
            "manual_web01": "NOT_RUN",
            "manual_web02": "NOT_RUN",
            "stage_status_updated": False,
        }
        publish_report(args.output, report)
    except ValueError as error:
        # Never echo user-supplied executable/report paths, private file data or host information.
        parser.error(str(error))
    print("Synthetic browser matrix recorded locally; never a physical WEB-01/02 PASS.")
    return 0 if all(x["status"] == "AUTOMATED_PASS" for x in outcomes.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
