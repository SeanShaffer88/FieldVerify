import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import fieldverify as fv  # noqa: E402

PY = sys.executable


def cmd(code, expect=0):
    return {"id": "c", "title": "cmd", "kind": "command",
            "argv": [PY, "-c", code], "expect_exit": expect}


class CheckTests(unittest.TestCase):
    def test_command_pass(self):
        r = fv.run_check(cmd("import sys; sys.exit(0)"))
        self.assertEqual(r["status"], "PASS"); self.assertEqual(r["exit_code"], 0)

    def test_command_fail_exit(self):
        r = fv.run_check(cmd("import sys; sys.exit(3)"))
        self.assertEqual(r["status"], "FAIL"); self.assertEqual(r["exit_code"], 3)

    def test_command_expect_list(self):
        c = cmd("import sys; sys.exit(2)"); c["expect_exit"] = [0, 2]
        self.assertEqual(fv.run_check(c)["status"], "PASS")

    def test_command_captures_output(self):
        r = fv.run_check(cmd("print('hello-out')"))
        self.assertIn("hello-out", r["stdout"])

    def test_file_exists_and_missing_and_min_size(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "f.bin"; p.write_bytes(b"x" * 100)
            ok = {"id": "f", "title": "f", "kind": "file_exists", "path": str(p)}
            self.assertEqual(fv.run_check(ok)["status"], "PASS")
            small = dict(ok, min_size=1000)
            self.assertEqual(fv.run_check(small)["status"], "FAIL")
            missing = dict(ok, path=str(Path(td) / "nope"))
            self.assertEqual(fv.run_check(missing)["status"], "FAIL")

    def test_file_contains_case_options(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.txt"; p.write_text("Hello World", encoding="utf-8")
            base = {"id": "fc", "title": "fc", "kind": "file_contains", "path": str(p), "needle": "Hello"}
            self.assertEqual(fv.run_check(base)["status"], "PASS")
            lower = dict(base, needle="hello")  # case-sensitive by default
            self.assertEqual(fv.run_check(lower)["status"], "FAIL")
            ci = dict(base, needle="hello", case_sensitive=False)
            self.assertEqual(fv.run_check(ci)["status"], "PASS")
            absent = dict(base, needle="missing")
            self.assertEqual(fv.run_check(absent)["status"], "FAIL")

    def test_env_var(self):
        os.environ["FV_TEST_VAR"] = "abc"
        try:
            base = {"id": "e", "title": "e", "kind": "env_var", "name": "FV_TEST_VAR"}
            self.assertEqual(fv.run_check(base)["status"], "PASS")
            self.assertEqual(fv.run_check(dict(base, equals="abc"))["status"], "PASS")
            self.assertEqual(fv.run_check(dict(base, equals="xyz"))["status"], "FAIL")
            self.assertEqual(fv.run_check(dict(base, name="FV_DEFINITELY_MISSING_123"))["status"], "FAIL")
        finally:
            del os.environ["FV_TEST_VAR"]

    def test_manual_noninteractive_skips(self):
        r = fv.run_check({"id": "m", "title": "m", "kind": "manual", "prompt": "Ok?"}, interactive=False)
        self.assertEqual(r["status"], "SKIPPED-MANUAL")

    def test_unknown_kind_fails_not_crashes(self):
        r = fv.run_check({"id": "u", "title": "u", "kind": "bogus"})
        self.assertEqual(r["status"], "FAIL")


class BundleTests(unittest.TestCase):
    def _run_cli(self, checks, *extra):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        cl = root / "checklist.json"; cl.write_text(json.dumps(checks), encoding="utf-8")
        out = root / "out"
        proc = subprocess.run([PY, str(ROOT / "fieldverify.py"), "run", str(cl),
                               "--out", str(out), *extra],
                              capture_output=True, text=True)
        return td, root, out, proc

    def test_bundle_contents_and_report_counts(self):
        checks = [cmd("pass"), {"id": "m", "title": "manual one", "kind": "manual", "prompt": "Ok?"}]
        checks[0]["title"] = "passing command"
        td, root, out, proc = self._run_cli(checks)
        with td:
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("[2/2]", proc.stdout); self.assertIn("100%", proc.stdout)
            payload = json.loads((out / "results.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["counts"], {"PASS": 1, "FAIL": 0, "SKIPPED-MANUAL": 1, "total": 2})
            self.assertIn("hostname", payload["machine"]); self.assertIn("python_version", payload["machine"])
            report = (out / "report.md").read_text(encoding="utf-8")
            self.assertIn("PASS", report); self.assertIn("SKIPPED-MANUAL", report)
            self.assertTrue((out / "logs").exists())

    def test_exit_code_aggregation_on_fail(self):
        td, root, out, proc = self._run_cli([cmd("import sys; sys.exit(1)")])
        with td:
            self.assertEqual(proc.returncode, 1)
            payload = json.loads((out / "results.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["counts"]["FAIL"], 1)

    def test_zip_bundle(self):
        td, root, out, proc = self._run_cli([cmd("pass")], "--zip")
        with td:
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((root / "out.zip").exists())

    def test_init_writes_parseable_checklist(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "starter.json"
            proc = subprocess.run([PY, str(ROOT / "fieldverify.py"), "init", "--out", str(target)],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            checks = fv.load_checklist(target)
            self.assertGreaterEqual(len(checks), 1)


if __name__ == "__main__":
    unittest.main()
