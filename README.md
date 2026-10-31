# StorageCleaner

**AI-assisted disk cleanup for Windows** — reclaims caches, crash dumps, old Windows
update leftovers, and rebuildable dev caches. A trained scoring model ranks
candidates, but a hard safety layer has the final say: the model can *promote*
safe candidates, never override a veto.

![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078d4)
![Python](https://img.shields.io/badge/python-3.8%2B-3776ab)
![Tests](https://img.shields.io/badge/tests-151%20passing-2ea44f)
![Brain](https://img.shields.io/badge/AI-brain%20v9%20MLP-8250df)
![License](https://img.shields.io/badge/license-MIT-2ea44f)

Pure Python standard library + numpy. No install step, no background service,
no telemetry. Deletion always asks first unless you pass `-q`.

---

## Contents

- [Quick start](#quick-start)
- [What it cleans](#what-it-cleans)
- [What it will never touch](#what-it-will-never-touch)
- [Old Windows files](#old-windows-files)
- [Why your PC boots slowly on battery](#why-your-pc-boots-slowly-on-battery)
- [How it works](#how-it-works)
- [Performance](#performance)
- [Project layout](#project-layout)
- [Known limits](#known-limits)

## Quick start

```bat
python StorageCleaner.py --report       :: scan only — shows reclaimable space, deletes nothing
python StorageCleaner.py                :: scan, then ask before cleaning
python StorageCleaner.py -q             :: clean SAFE items without asking
python StorageCleaner.py --deep         :: + old Windows files, update cache, deeper hunter
python StorageCleaner.py --aggressive   :: + rebuildable SDK/extension caches
python StorageCleaner.py --performance  :: power / startup / disk report (no deletion)
python StorageCleaner.py --fix-power    :: re-enable full CPU speed on battery (admin)
python StorageCleaner.py --explain PATH :: why is this path (not) considered junk
```

Or double-click a launcher:

| Launcher | Runs | Needs admin |
|---|---|---|
| `Clean-Report.bat` | `--deep --report` | no |
| `Clean-Deep.bat` | `--deep` | recommended |
| `Clean-Aggressive.bat` | `--aggressive` | yes |
| `Clean-Performance.bat` | `--performance` | no |

> Tip: right-click `Clean-Deep.bat` → **Run as administrator** to also clean
> `Windows.old`, `MEMORY.DMP` and other protected system targets.

Inspect any path without touching anything:

```bat
python StorageCleaner.py --explain "C:\Users\you\AppData\Local\SomeApp\Cache"
```

Prints the veto verdict, whether the name matches a cache pattern, size, age,
model score, and the final decision.

## What it cleans

| Family | Examples | Mode |
|---|---|---|
| Editor & browser caches | VS Code / Trae / Cursor `Cache`, `GPUCache`, `Crashpad`; Chrome/Edge/Brave profile caches | SAFE |
| Dev package caches | npm, pip, gradle, nuget, pnpm, uv, cargo, maven, Hugging Face | SAFE |
| AI CLI leftovers | `.claude`, `.codex`, `.kilo`, opencode tool-output (sessions stay) | SAFE |
| Windows caches | Update download cache, Delivery Optimization, INetCache, thumbcache, D3DSCache, GPU shader caches | SAFE–DEEP |
| Crash dumps | `MEMORY.DMP`, `Minidump`, `LiveKernelReports`, WER, `CrashDumps` | SAFE–DEEP |
| Temp | user temp, `C:\Windows\Temp`, installer temps, loose `.tmp/.bak/.dmp/.log` files | SAFE |
| Session sweeps | AI-tool sessions and logs **older than 7/30 days only** | FULL |
| **Old Windows files** | `Windows.old`, `$Windows.~BT`, `$Windows.~WS`, `$GetCurrent`, `$SysReset`, `$WinREAgent`, `Windows\Logs` >30d | DEEP |
| Rebuildable SDK state | VS Code extension data, Python user packages, npm globals, AVD caches, VS `Package Cache` | AGGRESSIVE |

> **Never cleaned on purpose:** `C:\Windows\Prefetch`. Deleting it makes the
> *next* boots slower while Windows rebuilds it — any "cleaner" that wipes
> Prefetch is optimizing its own report, not your PC.

## What it will never touch

A `safety_veto()` check runs **before** the model and before any name matching.
Anything it rejects is never deleted, whatever the model says.

- **Your data** — `Downloads`, `Documents`, `Pictures`, `Videos`, `Music`,
  `Desktop`, `OneDrive`, `.ssh`, `.aws`, `.gnupg`.
- **Installed apps** — `AppData\Local\Programs`, `AppData\Local\Packages`,
  and any Python `site-packages` tree (pip `--user`, uv tool envs, venvs —
  real packages can be *named* like caches, e.g. `propcache`, `diskcache`).
- **State folders** — `Recent`, `Themes`, `Signatures`, `Cookies`, `Login Data`,
  `IndexedDB`, `globalStorage`, `workspaceStorage`, session/task stores, …
- **Any folder holding a state file** at its top level (`.db`, `.json`, `.exe`,
  `.dll`, `.pem`, `.key`, …).

A folder whose own name is unambiguously scratch (`Cache`, `GPUCache`, `logs`,
`Temp`, `Crashpad`, …) is exempt from the content check — a cache may
legitimately contain a `.db` manifest.

<details>
<summary><strong>How the trained model is kept on a leash</strong></summary>

The MLP scores a folder 0–1 for "is this scratch space". It can only *promote*
a candidate that already passed the veto — it can never override it. `train_model.py`
refuses to ship a new brain unless it passes an acceptance gate:

- **zero** false positives on a 39-path hard-negative set of real user/system state
- hard-positive recall ≥ 0.90 on 25 name-ambiguous caches
- holdout F1 **below** 0.9995 — a perfect score means the model memorized
  templates instead of learning the concept, and is rejected

`legacy/model-v8.json` is the previous, unsafe brain (holdout F1 1.000 — it
flagged `Recent` and `Themes`). Kept as a cautionary reference; do not restore it.

</details>

## Old Windows files

After a feature update or PC reset, Windows keeps the old system so you can
roll back. Those folders are often **10–40 GB** and this tool removes them in
DEEP mode (admin): `Windows.old` is deleted with a recursive
`takeown` + `icacls` from TrustedInstaller and can take a few minutes.

> ⚠️ Deleting them **ends the rollback window** for that update. If the update
> is days old and you are not sure about it, wait the ~10 days Windows keeps
> the folders before cleaning them.

## Why your PC boots slowly on battery

The classic *"fast on charger, slow on battery"* symptom is **Windows power
throttling**, not junk files: the moment the charger is unplugged, CPU boost
mode gets disabled and the power-mode overlay is clamped to *Best battery* —
the CPU runs at base clock for everything, including boot. No amount of
cache cleaning changes this.

1. **Diagnose** — `Clean-Performance.bat` (or `--performance`) reports the
   power scheme, CPU boost on charger *vs* battery, Fast Startup, every
   startup program with on/off state, and disk headroom. Deletes nothing.
2. **Fix** — `--fix-power` asks for admin (UAC) once and re-enables CPU boost
   on battery, plus sets the battery power mode to *Balanced* when run while
   on battery. Re-run `--performance` to verify.
3. **Startup apps** — the report lists them; disable the ones you don't need
   in Task Manager → Startup apps.

## How it works

<details open>
<summary><strong>Discovery</strong></summary>

Two layers:

1. **Explicit targets** — ~530 known cache paths (editors, browsers, dev
   package managers, Electron apps, Windows caches, crash dumps, AI CLIs).
2. **Discovery walk** — a bounded walk of `AppData` (depth 3 in SAFE mode,
   deeper with `--deep`/`--aggressive`) matching folder names against cache
   patterns. This catches caches of apps the hardcoded list has never heard
   of. Every candidate must pass `safety_veto()`.

Discovery runs in **every** mode.
</details>

<details>
<summary><strong>The brain</strong></summary>

`model.json` holds a small MLP: 512 hashed path tokens + 20 structural
features → 192 ReLU → 48 ReLU → 1 sigmoid. `knowledge.json` holds the learned
token vocabulary and honest metrics. Retrain on this machine with:

```bat
python train_model.py
```

Training harvests real labeled directories, adds deliberately confusable
synthetic cases (a junk folder named `recent`, a keep folder named `Cache`),
then applies the acceptance gate above. If the gate fails, the old model is
kept and nothing is overwritten.
</details>

## Performance

Measured on the author's machine (cold / warm, SAFE mode):

| | v6 | v9 |
|---|---|---|
| Scan | 168 s / 39.4 s | 36 s / 8.9 s |
| Reclaimable found | 10.00 GB | 10.89 GB |
| Targets | 532 | 819 |

What made the difference: `os.scandir`-based sizing (no per-entry symlink
lstat), model weights parsed once per process, target sizing across a
16-thread pool, and report-only folders measured only under `--report`.

## Project layout

```text
StorageCleaner/
├── StorageCleaner.py        the cleaner (entry point, all modes)
├── train_model.py           brain training + acceptance gate
├── test_suite.py            151 checks: veto, coverage, model, speed
├── model.json               trained weights (brain v9)
├── knowledge.json           learned token vocabulary + metrics
├── Clean-Report.bat         double-click launchers
├── Clean-Deep.bat
├── Clean-Aggressive.bat
├── Clean-Performance.bat
└── legacy/                  pre-v9 sources and the unsafe v8 brain (reference)
```

Run the tests with `python test_suite.py` — exit code 0 means everything passed.

## Known limits

- **Windows only.** Paths and recycle-bin logic are Windows-specific.
- **The model is advisory.** Deletion is decided by the explicit target list,
  the discovery name patterns, and the veto; the model only adds candidates
  in `--aggressive` mode.
- **Admin rights** are needed for `Windows.old` & friends, `MEMORY.DMP`,
  `$PatchCache$`. Without elevation those report `requires admin` and are skipped.
- Some cache-looking folders are deliberately refused because they hold real
  state: `.DICloakCache` (browser profiles), `Qoder\SharedClientCache`
  (`.info.json` state), `EpicGamesLauncher\Saved\webcache_4430` (cookies).
- `Windows\Prefetch` is intentionally absent — see the note above.

## License

[MIT](LICENSE) © 2026 abhrajyoti-01 — free to use, modify and redistribute.

Note: this tool deletes files by design. The MIT "AS IS" warranty disclaimer
applies — review the `--report` output before cleaning, and keep anything
valuable backed up.
