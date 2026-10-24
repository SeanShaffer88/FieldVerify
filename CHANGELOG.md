# Changelog

## 0.1.0 — 2026-10-24

- Initial release: `fieldverify.py` CLI (`run` + `init`), stdlib only, Python 3.10+.
- Check kinds: `command` (argv + expected exit code(s)), `file_exists` (optional minimum size), `file_contains` (optional case sensitivity), `env_var` (optional expected value), and `manual` (SKIPPED-MANUAL non-interactively, y/n/skip with `--interactive`).
- Live progress with percentage, per-check timing, full stdout/stderr in `logs/`, truncated output in the report, `results.json` + `report.md` with PASS / FAIL / SKIPPED-MANUAL counts and machine info, optional `--zip` bundle, exit 1 on any FAIL.
- Examples: `winrecovery-smoke.json`, `modernflyouts-install.json`, `safereturn-basics.json` (template paths).
- unittest suite covering all check kinds, manual skipping, bundle contents, and exit-code aggregation.
