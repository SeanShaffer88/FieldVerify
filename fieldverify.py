#!/usr/bin/env python3
"""FieldVerify — on-machine verification runner (stdlib only, Python 3.10+).

Runs a JSON checklist sequentially, captures evidence, and writes
results.json + report.md (+ optional .zip bundle).

Check kinds:
  command      argv list, expect_exit int or list[int]
  file_exists  path, optional min_size
  file_contains path, needle, optional case_sensitive (default true)
  env_var      name, optional equals
  manual       prompt — SKIPPED-MANUAL non-interactively; y/n/skip with --interactive
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

__version__ = "0.1.0"
TRUNCATE = 8000

STARTER = [
    {"id": "python-version", "title": "Python runs a command", "kind": "command",
     "argv": ["python", "--version"], "expect_exit": 0, "timeout_sec": 30},
    {"id": "home-exists", "title": "A file exists (edit this path)", "kind": "file_exists",
     "path": "C:/path/to/some-file.txt", "notes": "Template — replace with a real path."},
    {"id": "confirm-visual", "title": "Visually confirm something", "kind": "manual",
     "prompt": "Open the app and confirm the main window renders correctly. Pass?"},
]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def machine_info() -> dict:
    return {
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "hostname": socket.gethostname(),
        "timestamp": _utcnow(),
    }


def _expect_exit_ok(actual: int, expect) -> bool:
    if isinstance(expect, list):
        return actual in expect
    return actual == int(expect if expect is not None else 0)


def run_check(check: dict, interactive: bool = False, log_dir: Path | None = None) -> dict:
    start = time.monotonic()
    result = {
        "id": check.get("id", "?"), "title": check.get("title", check.get("id", "?")),
        "kind": check.get("kind", "?"), "status": "FAIL", "detail": "",
        "duration_sec": 0.0, "notes": check.get("notes", ""),
        "stdout": "", "stderr": "", "exit_code": None,
    }
    kind = check.get("kind")
    timeout = check.get("timeout_sec", 60)
    try:
        if kind == "command":
            argv = check.get("argv")
            if not isinstance(argv, list) or not argv:
                result["detail"] = "command check requires non-empty argv list"
            else:
                proc = subprocess.run([str(a) for a in argv], capture_output=True,
                                      text=True, timeout=timeout)
                out, err = proc.stdout or "", proc.stderr or ""
                result["stdout"], result["stderr"] = out[:TRUNCATE], err[:TRUNCATE]
                result["exit_code"] = proc.returncode
                if log_dir is not None:
                    log_dir.mkdir(parents=True, exist_ok=True)
                    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(result["id"]))
                    (log_dir / f"{safe}.stdout.log").write_text(out, encoding="utf-8", errors="replace")
                    (log_dir / f"{safe}.stderr.log").write_text(err, encoding="utf-8", errors="replace")
                ok = _expect_exit_ok(proc.returncode, check.get("expect_exit", 0))
                result["status"] = "PASS" if ok else "FAIL"
                result["detail"] = f"exit {proc.returncode}, expected {check.get('expect_exit', 0)}"
        elif kind == "file_exists":
            p = Path(os.path.expandvars(str(check.get("path", "")))).expanduser()
            if not p.exists():
                result["detail"] = f"not found: {p}"
            elif check.get("min_size") is not None and p.is_file() and p.stat().st_size < int(check["min_size"]):
                result["detail"] = f"too small: {p.stat().st_size} < {check['min_size']} bytes: {p}"
            else:
                result["status"] = "PASS"
                result["detail"] = f"exists: {p}" + (f" ({p.stat().st_size} bytes)" if p.is_file() else "")
        elif kind == "file_contains":
            p = Path(os.path.expandvars(str(check.get("path", "")))).expanduser()
            needle = str(check.get("needle", ""))
            if not p.is_file():
                result["detail"] = f"file not found: {p}"
            else:
                text = p.read_text(encoding="utf-8", errors="replace")
                cs = bool(check.get("case_sensitive", True))
                found = needle in text if cs else needle.lower() in text.lower()
                result["status"] = "PASS" if found else "FAIL"
                result["detail"] = (f"found {needle!r} in {p}" if found else
                                     f"{needle!r} not found in {p} (case_sensitive={cs})")
        elif kind == "env_var":
            name = str(check.get("name", ""))
            val = os.environ.get(name)
            if val is None:
                result["detail"] = f"environment variable not set: {name}"
            elif check.get("equals") is not None and val != str(check["equals"]):
                result["detail"] = f"{name}={val!r}, expected {check['equals']!r}"
            else:
                result["status"] = "PASS"
                result["detail"] = f"{name} is set" + (f" = {val!r}" if check.get("equals") is not None else "")
        elif kind == "manual":
            prompt = str(check.get("prompt", check.get("title", "Manual check")))
            if not interactive:
                result["status"] = "SKIPPED-MANUAL"
                result["detail"] = f"manual check skipped (non-interactive): {prompt}"
            else:
                try:
                    ans = input(f"  MANUAL [{result['id']}] {prompt} [y/n/skip]: ").strip().lower()
                except EOFError:
                    ans = "skip"
                if ans in ("y", "yes"):
                    result["status"], result["detail"] = "PASS", "operator answered yes"
                elif ans in ("n", "no"):
                    result["status"], result["detail"] = "FAIL", "operator answered no"
                else:
                    result["status"], result["detail"] = "SKIPPED-MANUAL", "operator skipped"
        else:
            result["detail"] = f"unknown kind: {kind!r}"
    except subprocess.TimeoutExpired as exc:
        result["detail"] = f"timed out after {timeout}s"
        result["stdout"] = (exc.stdout or "")[:TRUNCATE] if isinstance(exc.stdout, str) else ""
        result["stderr"] = (exc.stderr or "")[:TRUNCATE] if isinstance(exc.stderr, str) else ""
    except Exception as exc:  # a broken check is a FAIL, not a crash
        result["detail"] = f"error: {type(exc).__name__}: {exc}"
    result["duration_sec"] = round(time.monotonic() - start, 3)
    return result


def load_checklist(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    checks = data.get("checks") if isinstance(data, dict) else data
    if not isinstance(checks, list):
        raise ValueError("checklist must be a JSON list, or an object with a 'checks' list")
    return checks


def render_report(payload: dict) -> str:
    counts, info = payload["counts"], payload["machine"]
    lines = [
        "# FieldVerify Report", "",
        f"- Timestamp: {info['timestamp']}",
        f"- Hostname: {info['hostname']}",
        f"- Platform: {info['platform']}",
        f"- Python: {info['python_version']}",
        f"- Checklist: {payload.get('checklist', '')}", "",
        "## Summary", "",
        "| Result | Count |", "|---|---:|",
        f"| PASS | {counts['PASS']} |", f"| FAIL | {counts['FAIL']} |",
        f"| SKIPPED-MANUAL | {counts['SKIPPED-MANUAL']} |", f"| Total | {counts['total']} |", "",
        "## Checks", "",
        "| # | Status | Check | Duration | Detail |", "|---:|---|---|---:|---|",
    ]
    for i, r in enumerate(payload["results"], 1):
        detail = str(r["detail"]).replace("|", "\\|").replace("\n", " ")
        title = str(r["title"]).replace("|", "\\|")
        lines.append(f"| {i} | {r['status']} | {title} (`{r['id']}`) | {r['duration_sec']}s | {detail} |")
    lines += ["", "## Detail", ""]
    for r in payload["results"]:
        lines += [f"### {r['status']} — {r['title']} (`{r['id']}`, {r['kind']})", "",
                  f"- Duration: {r['duration_sec']}s", f"- Detail: {r['detail']}"]
        if r.get("exit_code") is not None:
            lines.append(f"- Exit code: {r['exit_code']}")
        if r.get("notes"):
            lines.append(f"- Notes: {r['notes']}")
        if r.get("stdout"):
            lines += ["", "stdout (truncated):", "", "```", r["stdout"][:2000], "```"]
        if r.get("stderr"):
            lines += ["", "stderr (truncated):", "", "```", r["stderr"][:2000], "```"]
        lines.append("")
    return "\n".join(lines) + "\n"


def run_checklist(checklist_path: Path, out_dir: Path, interactive: bool = False,
                  make_zip: bool = False) -> tuple[dict, int]:
    checks = load_checklist(checklist_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir = out_dir / "logs"
    results = []
    total = len(checks)
    for i, check in enumerate(checks, 1):
        r = run_check(check, interactive=interactive, log_dir=log_dir)
        results.append(r)
        pct = round(i * 100 / total) if total else 100
        print(f"[{i}/{total}] {r['status']} {r['title']} ({r['duration_sec']}s) — {pct}%", flush=True)
    counts = {"PASS": sum(1 for r in results if r["status"] == "PASS"),
              "FAIL": sum(1 for r in results if r["status"] == "FAIL"),
              "SKIPPED-MANUAL": sum(1 for r in results if r["status"] == "SKIPPED-MANUAL"),
              "total": total}
    payload = {"tool": "fieldverify", "version": __version__, "checklist": str(checklist_path),
               "machine": machine_info(), "counts": counts, "results": results}
    (out_dir / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    if make_zip:
        # Zip the out_dir contents into <out_dir-name>.zip beside it.
        archive = out_dir.parent / f"{out_dir.name}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(out_dir.rglob("*")):
                if f.is_file():
                    zf.write(f, f.relative_to(out_dir.parent))
        payload["bundle"] = str(archive)
        (out_dir / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nDone: {counts['PASS']} PASS, {counts['FAIL']} FAIL, "
          f"{counts['SKIPPED-MANUAL']} SKIPPED-MANUAL of {total}. "
          f"Report: {out_dir / 'report.md'}")
    return payload, (1 if counts["FAIL"] else 0)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fieldverify", description="On-machine verification runner.")
    ap.add_argument("--version", action="version", version=f"fieldverify {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="Run a checklist")
    r.add_argument("checklist")
    r.add_argument("--out", default="fieldverify-out")
    r.add_argument("--interactive", action="store_true", help="Ask y/n/skip for manual checks")
    r.add_argument("--zip", action="store_true", help="Also write a .zip bundle beside --out")
    i = sub.add_parser("init", help="Write a starter checklist")
    i.add_argument("--out", default="fieldverify.json")
    args = ap.parse_args(argv)
    if args.cmd == "init":
        out = Path(args.out)
        if out.exists():
            print(f"refusing to overwrite existing {out}", file=sys.stderr); return 2
        out.write_text(json.dumps({"checks": STARTER}, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote starter checklist to {out} — edit the paths, then: "
              f"python fieldverify.py run {out}")
        return 0
    try:
        _, code = run_checklist(Path(args.checklist), Path(args.out),
                                interactive=args.interactive, make_zip=args.zip)
        return code
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
