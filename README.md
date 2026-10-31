# StorageCleaner v9.1

Windows disk cleanup with a trained scoring model and a hard safety layer.
Pure Python standard library plus numpy. No install step, no service, no telemetry.

## Quick start

```
python StorageCleaner.py --report      # scan and show what is reclaimable, delete nothing
python StorageCleaner.py               # scan, then ask before cleaning
python StorageCleaner.py -q            # clean SAFE items without asking
python StorageCleaner.py --full        # also recycle bin, old sessions, playwright
python StorageCleaner.py --deep        # deeper discovery + extra caches + --full
python StorageCleaner.py --aggressive  # DEEP + rebuildable SDK/extension caches
python StorageCleaner.py --performance # power/startup/disk report: why boot is slow
python StorageCleaner.py --fix-power   # re-enable full CPU speed on battery (admin)
```

Or double-click a launcher:

| Launcher | Equivalent |
|---|---|
| `CleanerV6_REPORT.bat` | `--report` |
| `CleanerV6_DEEP.bat` | `--deep` |
| `CleanerV6_AGGRESSIVE.bat` | `--aggressive` |
| `CleanerV6_PERFORMANCE.bat` | `--performance` |

Inspect a single path without touching anything:

```
python StorageCleaner.py --explain "C:\Users\you\AppData\Local\SomeApp\Cache"
```

That prints the veto result, whether the name matches a cache pattern, the size,
the age, the model score, and the final verdict.

## What it will never touch

A `safety_veto()` check runs **before** the model and before any name matching.
Anything it rejects is never deleted, whatever the model says. It blocks:

- Your user data: `Downloads`, `Documents`, `Pictures`, `Videos`, `Music`,
  `Desktop`, `OneDrive`, `.ssh`, `.aws`, `.gnupg`.
- Installed applications and packaged-app state: `AppData\Local\Programs`,
  `AppData\Local\Packages`.
- State folders: `Recent`, `Themes`, `Signatures`, `Templates`, `LocalState`,
  `globalStorage`, `workspaceStorage`, `sessions`, `tasks`, `projects`, `bin`,
  `lib`, `src`, `extensions`, `config`, `settings`, `Cookies`, `Login Data`,
  `Local Storage`, `IndexedDB`, `Bookmarks`.
- Any folder holding a state file at its top level (`.db`, `.json`, `.toml`,
  `.exe`, `.dll`, `.img`, `.jar`, `.lnk`, `.theme`, `.cdp`, `.pem`, `.key`).

A folder whose own name is unambiguously scratch (`Cache`, `Code Cache`,
`GPUCache`, `logs`, `Temp`, `Crashpad`, `htmlcache`, ...) is exempt from the
state-file check, because a cache may legitimately contain a `.db` or `.json`
manifest.

The model can only *promote* a candidate that already passed the veto. It can
never override it. A badly trained model makes this tool annoying, not
destructive.

## Old Windows files (v9.1, DEEP mode only)

After a Windows feature update or reset, the old system is kept so you can
roll back: `C:\Windows.old`, `C:\$Windows.~BT`, `C:\$Windows.~WS`,
`C:\$GetCurrent`, `C:\$SysReset`, `C:\$WinREAgent`. Together these are often
10-40 GB. `--deep` (and `--aggressive`) lists and deletes them, admin only.

Two honest warnings:

- Deleting them **ends the rollback window** for that update. If the update
  is fresh and you are not sure about it, wait the ~10 days Windows keeps it.
- They are owned by TrustedInstaller, so deletion takes ownership
  recursively (takeown + icacls) and can run several minutes on a big
  `Windows.old`.

`--deep` also ages out `C:\Windows\Logs` (CBS/DISM/WindowsUpdate logs) older
than 30 days.

## Why the PC boots slowly on battery (it is not junk)

The classic symptom "fast while charging, slow on battery" is **Windows
power throttling on DC**: CPU boost mode is disabled and the power-mode
overlay is clamped to *Best battery* whenever the laptop is unplugged. The
CPU runs at its base clock, so boot, logon and everything else crawl. No
amount of cache cleaning changes this.

- `--performance` shows the real state: power scheme, CPU boost on
  charger vs battery, fast startup, every startup program (with on/off
  state), and disk headroom. It deletes nothing.
- `--fix-power` asks for admin (UAC) once and re-enables CPU boost on
  battery, plus sets the battery power mode to *Balanced* when run while
  on battery. Re-run `--performance` to verify.

`C:\Windows\Prefetch` is deliberately **never** cleaned: deleting it makes
the *next* boots slower while Windows rebuilds it.

## How discovery works

Two layers:

1. **Explicit targets.** About 530 known cache paths (editors, browsers, dev
   package managers, Electron apps, Windows caches, crash dumps, AI CLI tools).
2. **Discovery walk.** A bounded walk of `AppData` (depth 3 in safe mode, deeper
   with `--deep`/`--aggressive`) that matches folder names against cache
   patterns. This is what catches caches belonging to apps the explicit list has
   never heard of.

Discovery runs in **every** mode. In v8 it only ran under `--deep`, which meant
safe mode was blind to any cache not in the hardcoded list.

## The brain

`model.json` holds a small MLP: 512 hashed path tokens + 20 structural features
-> 192 ReLU -> 48 ReLU -> 1 sigmoid. It scores a folder 0..1 for "is this
scratch space". `knowledge.json` holds the learned token vocabulary.

Retrain with:

```
python train_model.py
```

Training harvests real labeled directories from this machine, adds synthetic
confusable cases, and then runs an acceptance gate. The model is only written if:

- **zero** false positives on a 39-path hard-negative set of real user/system
  state (`Recent`, `Themes`, `ConnectedDevicesPlatform`, `Cookies`, `Login Data`,
  `globalStorage`, session stores, `Programs`, `LocalState`, ...),
- hard-positive recall >= 0.90 on 25 name-ambiguous caches
  (`BrowserCache`, `SharedClientCache`, `webcache_4430`, `htmlcache`, ...),
- holdout F1 is below 0.9995.

That last rule exists because v8 shipped with holdout accuracy 1.000 and F1
1.000 and was unsafe. A perfect score on this task means the model learned the
training templates, not the concept. A perfect score is now a rejection, not a
result.

`model.v8.json` is kept for reference. It is the unsafe model; do not restore it.

## Speed

Measured on this machine (cold / warm, safe mode):

| | v6 | v9 |
|---|---|---|
| Scan | 168 s / 39.4 s | 36 s / 8.9 s |
| Reclaimable found | 10.00 GB | 10.89 GB |
| Targets | 532 | 819 |

What made the difference: `dir_size()` on `os.scandir` instead of `os.walk`
(no per-entry symlink lstat), model weights parsed once per process instead of
per `ai_score()` call, target sizing across a 16-thread pool, and report-only
folders measured only under `--report` (they were 26.7 s of every scan and are
never deleted).

## Files

| File | Purpose |
|---|---|
| `StorageCleaner.py` | the cleaner |
| `train_model.py` | training + acceptance gate |
| `test_suite.py` | 130 checks: veto, coverage, model, speed |
| `model.json` | trained weights (brain v9) |
| `knowledge.json` | learned token vocabulary + honest metrics |
| `model.v8.json` | previous brain, kept for reference only |
| `*.py.bak` | pre-v9 sources, kept for rollback |

Run the tests with `python test_suite.py`. Exit code 0 means everything passed.

## Known limits

- Windows only. Paths and the recycle bin logic are Windows-specific.
- The model is advisory. Deletion is decided by the explicit target list, the
  discovery name patterns, and the veto; the model only adds candidates in
  `--aggressive` mode.
- Admin rights are needed for a few system targets (`MEMORY.DMP`, `$PatchCache$`,
  `Windows.old` and the other old-Windows folders). Without elevation those
  report `requires admin` and are skipped.
- Some folders that look like caches are deliberately refused because they hold
  real state: `.DICloakCache` (browser profiles), `Qoder\SharedClientCache`
  (`.info.json` state), `EpicGamesLauncher\Saved\webcache_4430` (cookies).
- The discovery hunter never enters any Python `site-packages` tree (pip
  `--user`, uv tool envs, venvs). Real packages can be *named* like caches
  (`propcache`, `diskcache`), and the bytecode caches inside regenerate on
  the next run anyway - deleting them buys nothing and slows Python down.
  In the cleaning output, discovered caches now show as one aggregate
  `hunt caches` line; the log keeps every individual path.
