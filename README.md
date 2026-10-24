## TL;DR

FieldVerify is a standalone, zero-dependency Python runner for verification that can only happen on a real machine. You describe checks in one JSON checklist — commands, files, environment variables, and manual prompts — run it in one sitting, and get back a bundle (`results.json` + `report.md` + logs, optionally zipped) that records exactly what passed, failed, or was skipped, and on what machine.

```bash
python fieldverify.py init                      # write a starter checklist
python fieldverify.py run fieldverify.json --out run1 --zip
python fieldverify.py run examples/safereturn-basics.json --interactive
```

Python 3.10+, standard library only. Windows, macOS, and Linux.

## Why

Projects accumulate checks that cannot run in CI or on a development VM: a DLL smoke test against live system data, a certificate-trust install, a restore drill. Left alone, each becomes its own owed manual session and its result lives in someone's memory. FieldVerify turns them into one checklist, one run, and one evidence bundle.

## Checklist format

A checklist is a JSON file: either a top-level list of checks, or an object with a `checks` list. Each check has `id`, `title`, and `kind`, plus kind-specific fields. `timeout_sec` (commands, default 60) and `notes` are optional on any check.

| Kind | Fields | Passes when |
|---|---|---|
| `command` | `argv` (list), `expect_exit` (int or list, default 0) | Process exits with an expected code |
| `file_exists` | `path`, optional `min_size` (bytes) | Path exists (and is at least `min_size`) |
| `file_contains` | `path`, `needle`, optional `case_sensitive` (default `true`) | File text contains the needle |
| `env_var` | `name`, optional `equals` | Variable is set (and equals the value, if given) |
| `manual` | `prompt` | Operator answers yes (interactive only) |

`manual` checks in non-interactive mode are recorded as `SKIPPED-MANUAL` — never silently passed. With `--interactive` they ask `y/n/skip` on the console.

### Full example

```json
{
  "checks": [
    {
      "id": "dll-exists",
      "title": "winrecovery.dll exists",
      "kind": "file_exists",
      "path": "C:/path/to/winrecovery.dll",
      "min_size": 1024
    },
    {
      "id": "smoke-test",
      "title": "Smoke test passes",
      "kind": "command",
      "argv": ["powershell", "-NoProfile", "-File", "C:/path/to/smoke-test.ps1"],
      "expect_exit": 0,
      "timeout_sec": 120
    },
    {
      "id": "env-ready",
      "title": "SystemDrive is set",
      "kind": "env_var",
      "name": "SystemDrive"
    },
    {
      "id": "visual-confirm",
      "title": "Main window renders",
      "kind": "manual",
      "prompt": "Open the app and confirm the main window renders correctly. Pass?"
    }
  ]
}
```

## Report and bundle

`run` prints live progress — `[3/12] PASS name (0.4s) — 25%` — runs checks sequentially, and exits `1` if any check fails (`2` for usage / checklist errors). The `--out` directory contains:

- `results.json` — machine-readable results: counts, per-check status / detail / duration / captured output, and machine info (platform, Python version, hostname, UTC timestamp).
- `report.md` — human-readable summary table (PASS / FAIL / SKIPPED-MANUAL counts) plus per-check detail.
- `logs/` — full, untruncated stdout/stderr per command check. In `results.json` and `report.md`, captured output is truncated to 8000 characters.

With `--zip`, the out directory is also archived as `<out>.zip` beside it — one file to send back as evidence.

## Examples

Three real checklists are in `examples/` — all use obvious template paths (`C:/path/to/...`) that you must edit before running:

- `examples/winrecovery-smoke.json` — `winrecovery.dll` exists, then run the PowerShell smoke test expecting exit 0.
- `examples/modernflyouts-install.json` — the signing `.cer` and `.msixbundle` exist, plus a manual check for the certificate-trust / install prompts.
- `examples/safereturn-basics.json` — build exists, `SystemDrive` is set, plus a manual restore-drill prompt.

## Security and limitations

- **FieldVerify runs whatever the checklist says.** Command checks execute arbitrary programs with your privileges. Review every checklist — especially one someone sent you — before running it, exactly as you would a script.
- Sample Windows paths are templates, not real locations; the examples will fail (by design) until you point them at real files.
- Manual checks depend on the operator's answer; a bundle proves a check was answered, not that the underlying observation was correct.
- Output truncation (8000 characters) applies to the report files only; full command output is preserved in `logs/`.
- FieldVerify does not elevate, install anything, or change system state itself — any change comes from the commands in your checklist.

## Development

```bash
python -m unittest discover -s tests -v
```

MIT — see `LICENSE`.
