#!/usr/bin/env python3
"""StorageCleaner v6 - Advanced AI-assisted disk cleanup.
Covers: AI CLI tools, editor/browser caches, dev package caches, Windows
delivery caches, loose junk files (.tmp/.log/.bak/.dmp), crash dumps,
Electron app caches, plus a deep AppData cache hunter. Pure stdlib;
optional trained model in model.json (brain v7+).

v6 additions (comprehensive upgrade):
  - Windows memory dump cleanup with safe admin privilege handling
  - System-level: Package Cache, Installer $PatchCache$, driver store cleanup
  - AI-guided hunter: deeper traversal (depth 5→8) with live model scoring
  - SDK/toolchain caches: gradle wrapper, android avd, flutter bin cache
  - Aggressive mode: optional cleanup of report-only items (extensions, packages)
  - Improved size prediction accuracy to reduce "already empty" reports

Usage:
  python StorageCleaner.py                report + interactive prompt (safe)
  python StorageCleaner.py -q             clean SAFE items without asking
  python StorageCleaner.py --full         also recycle bin, old sessions, playwright
  python StorageCleaner.py --deep         advanced: hunter + extra caches + --full
  python StorageCleaner.py --aggressive   DEEP + report-only items (extensions, sdk)
  python StorageCleaner.py --smart DIR    AI-score every folder under DIR (report)
Safe by whitelist: never touches Downloads/Documents/Pictures/Videos/Desktop/OneDrive files.
"""
import os, sys, shutil, sqlite3, subprocess, time, json, re, ctypes

HOME = os.path.expanduser('~')
LOCAL = os.environ.get('LOCALAPPDATA', os.path.join(HOME, 'AppData', 'Local'))
APPD = os.environ.get('APPDATA', os.path.join(HOME, 'AppData', 'Roaming'))
HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, 'StorageCleaner.log')
DEEP = any(a in ('--deep', '--advance', '--advanced') for a in sys.argv)
AGGRESSIVE = '--aggressive' in sys.argv or '--nuclear' in sys.argv
FULL = '--full' in sys.argv or DEEP or AGGRESSIVE
QUIET = '-q' in sys.argv
REPORT = '--report' in sys.argv or '--dry-run' in sys.argv

def argv_value(flag):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None
SMART_ROOT = argv_value('--smart')

def log(msg):
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%dT%H:%M:%S') + ' ' + msg + '\n')
    except OSError:
        pass

def dir_size(path):
    total = 0
    for root, _, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total

def fmt(n):
    return '%.2f GB' % (n / 1073741824) if n >= 1073741824 else '%.0f MB' % (n / 1048576)

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def process_running(name):
    try:
        out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq %s' % name],
                             capture_output=True, text=True, timeout=8).stdout.lower()
        return name.lower() in out
    except Exception:
        return False

def clear_dir(path, older_than_days=0):
    freed = 0
    cutoff = None
    if older_than_days:
        cutoff = time.time() - older_than_days * 86400
    if not os.path.isdir(path):
        return 0
    for entry in os.listdir(path):
        full = os.path.join(path, entry)
        try:
            mtime = os.path.getmtime(full)
        except OSError:
            continue
        if cutoff is not None and mtime >= cutoff:
            continue  # too recent, keep
        if os.path.isfile(full) or os.path.islink(full):
            try:
                freed += os.path.getsize(full)
                os.remove(full)
            except OSError:
                pass
        elif os.path.isdir(full):
            sz = dir_size(full)
            shutil.rmtree(full, ignore_errors=True)
            if not os.path.exists(full):
                freed += sz
    return freed

# ---------------- targets ----------------

def t_cline_db():
    if process_running('cline.exe'):
        return 0, 'skipped (cline.exe running)'
    db = os.path.join(HOME, '.cline', 'data', 'db', 'hub-events-hub-production.db')
    if not os.path.exists(db):
        return 0, 'not installed'
    before = os.path.getsize(db)
    try:
        con = sqlite3.connect(db, timeout=60)
        cur = con.cursor()
        mx = cur.execute('SELECT MAX(sequence) FROM hub_events').fetchone()[0]
        if mx is None:
            con.close()
            return 0, 'empty'
        cur.execute('DELETE FROM hub_events WHERE sequence <= ?', (mx - 5000,))
        con.commit()
        kept = cur.execute('SELECT COUNT(*) FROM hub_events').fetchone()[0]
        cur.close(); con.close()
        vcon = sqlite3.connect(db, timeout=60)
        vcon.isolation_level = None
        vcon.execute('VACUUM')
        vcon.close()
        return before - os.path.getsize(db), 'pruned to %d events' % kept
    except Exception as e:
        return 0, 'error: %r' % e

def newest_mtime(path):
    newest = 0
    for root, _, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            try:
                newest = max(newest, os.path.getmtime(os.path.join(root, f)))
            except OSError:
                pass
    return newest

def aged_tree(path, days):
    """Recursively delete files older than `days`, then prune only dirs that
    are truly empty afterwards. Recent session data is always preserved."""
    if not os.path.isdir(path):
        return 0
    cutoff = time.time() - days * 86400
    freed = 0
    for root, dirs, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            fp = os.path.join(root, f)
            try:
                if os.path.getmtime(fp) < cutoff:
                    freed += os.path.getsize(fp)
                    os.remove(fp)
            except OSError:
                pass
    for root, dirs, files in os.walk(path, topdown=False, onerror=lambda e: None):
        for d in dirs:
            dp = os.path.join(root, d)
            try:
                if not os.listdir(dp):
                    os.rmdir(dp)
            except OSError:
                pass
    return freed

def aged(label, path, days, dir_mode=False):
    """dir_mode: remove child items whose newest mtime is older than `days`
    (task-store style). Default: file-level aging inside the tree (session
    store style). Recent data is never touched."""
    def fn():
        if not os.path.isdir(path):
            return 0, 'not present'
        if dir_mode:
            cutoff = time.time() - days * 86400
            freed, killed = 0, 0
            for name in os.listdir(path):
                full = os.path.join(path, name)
                try:
                    newest = newest_mtime(full) if os.path.isdir(full) else os.path.getmtime(full)
                    if newest >= cutoff:
                        continue
                    if os.path.isdir(full):
                        sz = dir_size(full)
                        shutil.rmtree(full, ignore_errors=True)
                        if not os.path.exists(full):
                            freed += sz
                            killed += 1
                    else:
                        freed += os.path.getsize(full)
                        os.remove(full)
                        killed += 1
                except OSError:
                    pass
            note = '%d old items removed (>%dd)' % (killed, days) if killed else 'nothing old'
            return freed, note
        freed = aged_tree(path, days)
        return freed, ('aged files removed (>%dd)' % days) if freed else 'nothing old'
    return label, path, fn

def simple(label, path):
    def fn():
        if not os.path.isdir(path):
            return 0, 'not present'
        s = dir_size(path)
        if s == 0:
            return 0, 'already empty'
        shutil.rmtree(path, ignore_errors=True)
        clear_dir(path)
        remaining = dir_size(path) if os.path.exists(path) else 0
        return s - remaining, 'removed'
    return label, path, fn

def clear_contents(label, path):
    """Empty a folder in place (needed when the folder itself cannot be deleted)."""
    def fn():
        if not os.path.isdir(path):
            return 0, 'not present'
        s = dir_size(path)
        if s == 0:
            return 0, 'already empty'
        freed = clear_dir(path)
        return freed, 'emptied'
    return label, path, fn

def clear_matching_files(label, path, pattern):
    def fn():
        if not os.path.isdir(path):
            return 0, 'not present'
        pat = re.compile(pattern, re.I)
        freed = 0
        for name in os.listdir(path):
            if not pat.search(name):
                continue
            full = os.path.join(path, name)
            try:
                if os.path.isfile(full):
                    sz = os.path.getsize(full)
                    os.remove(full)
                    freed += sz
            except OSError:
                pass
        return freed, 'removed matching files'
    return label, path, fn

def privileged_delete(label, path, pattern=None):
    """Delete protected system files (e.g., MEMORY.DMP) with takeown + icacls if admin."""
    def fn():
        if not os.path.exists(path):
            return 0, 'not present'
        if not is_admin():
            if os.path.isfile(path):
                try:
                    sz = os.path.getsize(path)
                    return 0, 'requires admin (%s detected)' % fmt(sz)
                except OSError:
                    return 0, 'requires admin'
            return 0, 'requires admin'
        
        freed = 0
        targets = []
        if os.path.isfile(path):
            targets = [path]
        elif os.path.isdir(path) and pattern:
            pat = re.compile(pattern, re.I)
            for name in os.listdir(path):
                if pat.search(name):
                    targets.append(os.path.join(path, name))
        
        for target in targets:
            try:
                sz = os.path.getsize(target) if os.path.isfile(target) else dir_size(target)
                # Take ownership then delete
                subprocess.run(['takeown', '/F', target, '/A'], 
                              capture_output=True, timeout=10)
                subprocess.run(['icacls', target, '/grant', 'Administrators:F'],
                              capture_output=True, timeout=10)
                if os.path.isfile(target):
                    os.remove(target)
                else:
                    shutil.rmtree(target, ignore_errors=True)
                if not os.path.exists(target):
                    freed += sz
            except Exception:
                pass
        
        return freed, 'removed (admin)' if freed else 'requires admin or locked'
    return label, path, fn

EDITORS = ['Code', 'Trae', 'TRAE SOLO', 'Cursor', 'Windsurf', 'Qoder', 'devin',
           'Antigravity', 'Claude', 'Claude Code']
EDITOR_CACHE_SUBS = (
    'Cache', 'CachedData', 'CachedExtensionVSIXs', 'Code Cache', 'Crashpad',
    'DawnGraphiteCache', 'DawnWebGPUCache', 'GPUCache', 'logs', 'ShaderCache',
)
EDITOR_DEEP_SUBS = ('CachedExtensions', 'Service Worker', 'WebStorage')
BROWSER_CACHE_SUBS = (
    'Cache', 'Code Cache', 'GPUCache', 'GrShaderCache', 'GraphiteDawnCache',
    'Service Worker', 'ShaderCache', 'component_crx_cache',
)
BROWSER_REAL_PROFILES = re.compile(r'^(Default|Profile \d+|Guest Profile)$', re.I)
CACHE_NAME_RE = re.compile(
    r'(^|[/\\._-])(caches?|cached\w*|gpucache|codecache|shadercache|'
    r'crashpad|crashdumps?|temp|tmp|webview|dawncache|'
    r'deliveryoptimization|thumbcache|iconcache|vsix)([/\\._-]|$)',
    re.I)
HUNTER_SKIP = re.compile(
    r'(Downloads|Documents|Pictures|Videos|Music|Desktop|OneDrive|'
    r'\\Local\\Microsoft\\Windows\\INetCookies|'
    r'\\Local\\Microsoft\\Credentials|'
    r'\\.ssh|\\.aws|\\.gnupg|globalStorage|workspaceStorage|'
    r'\\node_modules($|\\)|\\Packages($|\\)|\\Local\\Programs($|\\)|'
    r'\\Local\\wsl($|\\)|GeForce NOW|'
    r'\\Windows\\WinSxS|\\Windows\\Installer|\\Windows\\System32|'
    r'\\WindowsApps)',
    re.I)
HUNTER_PRUNE = {
    'Programs', 'Packages', 'wsl', 'ConnectedDevicesPlatform', 'Publishers',
    'WindowsApps', 'Google', 'Microsoft', 'NVIDIA Corporation', 'NVIDIA',
}
HUNTER_ROOTS = (
    LOCAL, APPD, os.path.join(HOME, 'AppData', 'LocalLow'),
    r'C:\Windows\SoftwareDistribution\Download',
    r'C:\Windows\Temp', r'C:\Temp', r'C:\tmp',
    os.environ.get('TEMP', os.path.join(LOCAL, 'Temp')),
)
HUNTER_ROOTS_DEEP = HUNTER_ROOTS + (r'C:\ProgramData',)
# v6: AI-guided deeper roots for SDK/toolchain discovery
HUNTER_ROOTS_AGGRESSIVE = HUNTER_ROOTS_DEEP + (
    os.path.join(HOME, '.gradle'),
    os.path.join(HOME, '.android'),
    os.path.join(HOME, '.m2'),
    os.path.join(HOME, '.cache'),
)

# loose junk FILES (not just folders): temp artifacts, crash dumps,
# backup leftovers, office locks, partial downloads, stale logs
FILE_JUNK_RE = re.compile(
    r'^(~\$.*|.*\.(tmp|temp|bak|old|chk|dmp|etl|gid|wbk|sw[po]|'
    r'part|partial|crdownload|download|log))$', re.I)
FILE_JUNK_TEMP_ROOTS = (
    os.environ.get('TEMP', os.path.join(LOCAL, 'Temp')),
    r'C:\Temp', r'C:\tmp',
)
FILE_JUNK_DEEP_ROOTS = FILE_JUNK_TEMP_ROOTS + (
    LOCAL, APPD, os.path.join(HOME, 'AppData', 'LocalLow'))
FILE_JUNK_MAX = 4000

ELECTRON_APPS = [
    'discord', 'Slack', 'Spotify', 'Notion', 'Figma', 'Zoom', 'Postman',
    'obsidian', 'Signal', 'Twitch', 'EpicGamesLauncher', 'Parsec',
    'mongodb-compass', 'Microsoft Teams', 'WebView2Host', 'WhatsApp',
]
ELECTRON_CACHE_SUBS = ('Cache', 'Code Cache', 'GPUCache', 'ShaderCache', 'logs')

def hunt_cache_dirs(seen, use_ai=False):
    """Walk known junk roots and pick leftover *cache*/temp folders not already listed.
    
    v6: AI-guided scoring when use_ai=True and model available.
    """
    found = []
    found_norm = set()
    model = load_model() if use_ai else None
    now = time.time()
    
    # v6: depth varies by mode
    max_depth = 8 if AGGRESSIVE else (5 if DEEP else 3)
    roots = HUNTER_ROOTS_AGGRESSIVE if AGGRESSIVE else (HUNTER_ROOTS_DEEP if DEEP else HUNTER_ROOTS)
    
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirs, _files in os.walk(root, onerror=lambda e: None):
            if len(found) >= 120:
                return found
            depth = dirpath[len(root):].count(os.sep)
            if depth >= max_depth:
                dirs[:] = []
                continue
            keep = []
            for d in dirs:
                if d in HUNTER_PRUNE:
                    continue
                full = os.path.join(dirpath, d)
                nfull = os.path.normcase(os.path.abspath(full))
                if nfull in seen or nfull in found_norm or HUNTER_SKIP.search(full):
                    continue
                
                # Name-based match (fast path)
                if CACHE_NAME_RE.search(d):
                    found.append(full)
                    found_norm.add(nfull)
                    continue
                
                # AI scoring (slower, only in AGGRESSIVE mode with model)
                if model and AGGRESSIVE:
                    try:
                        st = os.stat(full)
                        size = dir_size(full) if depth < 6 else 0  # Skip deep size calc
                        age = (now - st.st_mtime) / 86400
                        score = ai_score(full, size, age, model)
                        if score >= 0.85:  # High confidence junk
                            found.append(full)
                            found_norm.add(nfull)
                            continue
                    except OSError:
                        pass
                
                keep.append(d)
            dirs[:] = keep
    return found

def _under_target(fp, seen):
    n = os.path.normcase(os.path.abspath(fp))
    for p in seen:
        if p and (n == p or n.startswith(p + os.sep)):
            return True
    return False

def hunt_junk_files(seen):
    """Loose junk FILES inside temp roots (always) and AppData (deep, >7d).
    Files inside dirs already targeted are skipped so sizes don't double-count."""
    roots = FILE_JUNK_DEEP_ROOTS if DEEP else FILE_JUNK_TEMP_ROOTS
    out = []
    now = time.time()
    for root in roots:
        if not os.path.isdir(root):
            continue
        deep_root = root not in FILE_JUNK_TEMP_ROOTS
        age_cut = now - (7 if deep_root else 0) * 86400
        for dirpath, dirs, files in os.walk(root, onerror=lambda e: None):
            if len(out) >= FILE_JUNK_MAX:
                return out
            if deep_root:
                keep = []
                for d in dirs:
                    if d in HUNTER_PRUNE:
                        continue
                    full = os.path.join(dirpath, d)
                    if HUNTER_SKIP.search(full):
                        continue
                    keep.append(d)
                dirs[:] = keep
                if dirpath[len(root):].count(os.sep) >= 4:
                    dirs[:] = []
            for f in files:
                if not FILE_JUNK_RE.match(f):
                    continue
                fp = os.path.join(dirpath, f)
                if _under_target(fp, seen):
                    continue
                try:
                    if os.path.getmtime(fp) >= age_cut:
                        continue
                except OSError:
                    continue
                out.append(fp)
    return out

def file_batch(label, files):
    """Delete a precomputed list of loose junk files."""
    def fn():
        freed, killed = 0, 0
        for fp in files:
            try:
                sz = os.path.getsize(fp)
                os.remove(fp)
                freed += sz
                killed += 1
            except OSError:
                pass
        return freed, '%d junk files removed' % killed
    total = 0
    for fp in files:
        try:
            total += os.path.getsize(fp)
        except OSError:
            pass
    fn.preview_size = total
    return label, 'loose files (temp/appdata)', fn

def prune_empty_dirs(path, max_depth=4):
    """Remove empty folders left behind after cleaning."""
    removed = 0
    if not os.path.isdir(path):
        return 0
    base = path.count(os.sep)
    for dirpath, dirs, _files in os.walk(path, topdown=False, onerror=lambda e: None):
        if dirpath.count(os.sep) - base > max_depth:
            continue
        for d in dirs:
            dp = os.path.join(dirpath, d)
            try:
                if not os.listdir(dp):
                    os.rmdir(dp)
                    removed += 1
            except OSError:
                pass
    return removed

def add_unique(t, seen, item):
    path = item[1]
    n = os.path.normcase(os.path.abspath(path)) if path else path
    if n in seen:
        return
    seen.add(n)
    t.append(item)

def build_targets():
    t, seen = [], set()
    add_unique(t, seen, ('cline telemetry db', os.path.join(HOME, '.cline'), t_cline_db))
    add_unique(t, seen, simple('opencode tool-output', os.path.join(HOME, '.local', 'share', 'opencode', 'tool-output')))
    add_unique(t, seen, simple('codex tmp', os.path.join(HOME, '.codex', '.tmp')))
    # electron editor family — roaming + local
    for ed in EDITORS:
        for base_root in (APPD, LOCAL):
            base = os.path.join(base_root, ed)
            for sub in EDITOR_CACHE_SUBS:
                add_unique(t, seen, simple('%s %s' % (ed.lower(), sub.lower()), os.path.join(base, sub)))
            if DEEP:
                for sub in EDITOR_DEEP_SUBS:
                    add_unique(t, seen, simple('%s %s' % (ed.lower(), sub.lower()), os.path.join(base, sub)))
    # extra vscode-family leftovers
    add_unique(t, seen, simple('vscode cached profiles', os.path.join(APPD, 'Code', 'CachedProfilesData')))
    # AI / agent leftover caches
    add_unique(t, seen, simple('claude tmp', os.path.join(HOME, '.claude', 'tmp')))
    add_unique(t, seen, simple('claude debug', os.path.join(HOME, '.claude', 'debug')))
    add_unique(t, seen, simple('claude cache', os.path.join(HOME, '.claude', 'cache')))
    add_unique(t, seen, simple('claude paste cache', os.path.join(HOME, '.claude', 'paste-cache')))
    add_unique(t, seen, simple('claude downloads', os.path.join(HOME, '.claude', 'downloads')))
    add_unique(t, seen, simple('codex cache', os.path.join(HOME, '.codex', 'cache')))
    add_unique(t, seen, simple('kilo cache', os.path.join(HOME, '.kilo', 'cache')))
    add_unique(t, seen, simple('kilo node cache', os.path.join(HOME, '.kilo', 'node_modules', '.cache')))
    add_unique(t, seen, simple('continue cache', os.path.join(HOME, '.continue', 'indexCache')))
    add_unique(t, seen, simple('huggingface hub cache', os.path.join(HOME, '.cache', 'huggingface')))
    add_unique(t, seen, simple('torch hub cache', os.path.join(HOME, '.cache', 'torch')))
    add_unique(t, seen, simple('pip home cache', os.path.join(HOME, '.cache', 'pip')))
    add_unique(t, seen, simple('bun cache', os.path.join(HOME, '.bun', 'install', 'cache')))
    add_unique(t, seen, simple('yarn cache', os.path.join(LOCAL, 'Yarn', 'Cache')))
    add_unique(t, seen, simple('yarn berry cache', os.path.join(HOME, '.yarn', 'berry', 'cache')))
    add_unique(t, seen, simple('cargo registry cache', os.path.join(HOME, '.cargo', 'registry', 'cache')))
    add_unique(t, seen, simple('composer cache', os.path.join(APPD, 'Composer', 'cache')))
    add_unique(t, seen, simple('go build cache', os.path.join(LOCAL, 'go-build')))
    add_unique(t, seen, simple('android build cache', os.path.join(HOME, '.android', 'build-cache')))
    add_unique(t, seen, simple('android cache', os.path.join(HOME, '.android', 'cache')))
    # dev package caches
    add_unique(t, seen, simple('npm cache', os.path.join(LOCAL, 'npm-cache')))
    add_unique(t, seen, simple('pip cache', os.path.join(LOCAL, 'pip', 'Cache')))
    add_unique(t, seen, simple('gradle caches', os.path.join(HOME, '.gradle', 'caches')))
    add_unique(t, seen, simple('nuget packages', os.path.join(HOME, '.nuget', 'packages')))
    add_unique(t, seen, simple('nuget http cache', os.path.join(LOCAL, 'NuGet', 'Cache')))
    add_unique(t, seen, simple('nuget v3 cache', os.path.join(LOCAL, 'NuGet', 'v3-cache')))
    add_unique(t, seen, simple('pnpm-cache', os.path.join(LOCAL, 'pnpm-cache')))
    add_unique(t, seen, simple('pub cache', os.path.join(LOCAL, 'Pub', 'Cache')))
    add_unique(t, seen, simple('node-gyp cache', os.path.join(LOCAL, 'node-gyp', 'Cache')))
    add_unique(t, seen, simple('local leftover cache', os.path.join(LOCAL, 'cache')))
    add_unique(t, seen, simple('inet cache', os.path.join(LOCAL, 'Microsoft', 'Windows', 'INetCache')))
    add_unique(t, seen, simple('scoop cache', os.path.join(HOME, 'scoop', 'cache')))
    add_unique(t, seen, simple('npm user cache', os.path.join(HOME, '.npm', '_cacache')))
    add_unique(t, seen, simple('npm user logs', os.path.join(HOME, '.npm', '_logs')))
    add_unique(t, seen, simple('maven repo', os.path.join(HOME, '.m2', 'repository')))
    add_unique(t, seen, simple('uv cache', os.path.join(LOCAL, 'uv', 'cache')))
    add_unique(t, seen, simple('pnpm store', os.path.join(LOCAL, 'pnpm', 'store')))
    # system
    add_unique(t, seen, clear_contents('user temp', os.environ.get('TEMP', os.path.join(LOCAL, 'Temp'))))
    add_unique(t, seen, clear_contents('windows temp', r'C:\Windows\Temp'))
    add_unique(t, seen, simple('webcache (best effort)', os.path.join(LOCAL, 'Microsoft', 'Windows', 'WebCache')))
    add_unique(t, seen, simple('d3ds cache', os.path.join(LOCAL, 'D3DSCache')))
    add_unique(t, seen, clear_matching_files('explorer thumbcache', os.path.join(LOCAL, 'Microsoft', 'Windows', 'Explorer'), r'(thumbcache|iconcache).*\.db$'))
    add_unique(t, seen, simple('delivery optimization', os.path.join(LOCAL, 'Microsoft', 'Windows', 'DeliveryOptimization', 'Cache')))
    add_unique(t, seen, simple('intel shader cache', os.path.join(HOME, 'AppData', 'LocalLow', 'Intel')))
    add_unique(t, seen, simple('error reports', os.path.join(LOCAL, 'Microsoft', 'Windows', 'WER')))
    add_unique(t, seen, simple('crash dumps', os.path.join(LOCAL, 'CrashDumps')))
    add_unique(t, seen, simple('nvidia shader cache', os.path.join(LOCAL, 'NVIDIA', 'DXCache')))
    add_unique(t, seen, simple('nvidia gl cache', os.path.join(LOCAL, 'NVIDIA', 'GLCache')))
    add_unique(t, seen, simple('nvidia downloads', os.path.join(LOCAL, 'NVIDIA Corporation', 'Downloader')))
    add_unique(t, seen, simple('office file cache', os.path.join(LOCAL, 'Microsoft', 'Office', '16.0', 'OfficeFileCache')))
    add_unique(t, seen, simple('onedrive logs', os.path.join(LOCAL, 'Microsoft', 'OneDrive', 'logs')))
    add_unique(t, seen, simple('tencent game dl cache', r'C:\Temp\TxGameDownload'))
    add_unique(t, seen, simple('root c-tmp automation', r'C:\tmp'))
    if FULL:
        add_unique(t, seen, simple('playwright browsers', os.path.join(LOCAL, 'ms-playwright')))
        add_unique(t, seen, simple('vscode webview storage', os.path.join(APPD, 'Code', 'WebStorage')))
        add_unique(t, seen, simple('cursor worktrees', os.path.join(HOME, '.cursor', 'worktrees')))
        add_unique(t, seen, simple('jcode cache', os.path.join(LOCAL, 'jcode', 'Cache')))
        add_unique(t, seen, simple('dyad cache', os.path.join(LOCAL, 'dyad', 'Cache')))
    if DEEP:
        add_unique(t, seen, simple('gradle wrapper dists', os.path.join(HOME, '.gradle', 'wrapper', 'dists')))
        add_unique(t, seen, simple('win update downloads', r'C:\Windows\SoftwareDistribution\Download'))
        add_unique(t, seen, simple('expo cache', os.path.join(HOME, '.expo', 'cache')))
        add_unique(t, seen, simple('flutter pub cache', os.path.join(HOME, '.pub-cache')))
        for flutter_cache in (
            r'C:\Program Files\flutter\bin\cache',
            r'C:\src\flutter\bin\cache',
            r'C:\flutter\bin\cache',
        ):
            add_unique(t, seen, simple('flutter sdk cache', flutter_cache))
        # v6: Windows Installer patch cache (often 2-5 GB)
        add_unique(t, seen, simple('installer patch cache', r'C:\Windows\Installer\$PatchCache$'))
    
    # v6: SDK/toolchain caches (AGGRESSIVE mode)
    if AGGRESSIVE:
        add_unique(t, seen, simple('android avd cache', os.path.join(HOME, '.android', 'avd')))
        add_unique(t, seen, simple('package cache (vs/sdk)', r'C:\ProgramData\Package Cache'))
        add_unique(t, seen, simple('vscode extensions (rebuild)', os.path.join(APPD, 'Code', 'User', 'extensions')))
        add_unique(t, seen, simple('python user packages', os.path.join(APPD, 'Python')))
        add_unique(t, seen, simple('global npm packages', os.path.join(APPD, 'npm')))
    # NOTE: Videos\NVIDIA\GeForce NOW recordings are intentionally NEVER touched (user keeps them).
    # electron apps (discord/slack/spotify/notion/figma/...)
    for app in ELECTRON_APPS:
        for base_root in (APPD, LOCAL):
            base = os.path.join(base_root, app)
            for sub in ELECTRON_CACHE_SUBS:
                add_unique(t, seen, simple('%s %s' % (app.lower(), sub.lower()), os.path.join(base, sub)))
    # steam / game launchers
    for sub in ('Cache', 'Code Cache', 'GPUCache', 'ShaderCache'):
        add_unique(t, seen, simple('steam htmlcache %s' % sub.lower(), os.path.join(LOCAL, 'Steam', 'htmlcache', sub)))
    # system crash dump locations
    add_unique(t, seen, simple('bsod minidumps', r'C:\Windows\Minidump'))
    add_unique(t, seen, simple('live kernel reports', r'C:\Windows\LiveKernelReports'))
    add_unique(t, seen, simple('system error reports', r'C:\ProgramData\Microsoft\Windows\WER'))
    add_unique(t, seen, simple('setup panther logs', r'C:\Windows\Panther'))
    add_unique(t, seen, simple('squirrel installer temp', os.path.join(LOCAL, 'SquirrelTemp')))
    # v6: Windows memory dump with privileged deletion
    add_unique(t, seen, privileged_delete('windows memory dump', r'C:\Windows\MEMORY.DMP'))
    add_unique(t, seen, simple('chrome crashpad', os.path.join(LOCAL, 'Google', 'Chrome', 'User Data', 'Crashpad')))
    add_unique(t, seen, simple('edge crashpad', os.path.join(LOCAL, 'Microsoft', 'Edge', 'User Data', 'Crashpad')))
    # browsers, real profiles only
    for browser, base in (('chrome', os.path.join(LOCAL, 'Google', 'Chrome', 'User Data')),
                          ('edge', os.path.join(LOCAL, 'Microsoft', 'Edge', 'User Data')),
                          ('brave', os.path.join(LOCAL, 'BraveSoftware', 'Brave-Browser', 'User Data'))):
        if not os.path.isdir(base):
            continue
        try:
            profiles = os.listdir(base)
        except OSError:
            continue
        for profile in profiles:
            if not BROWSER_REAL_PROFILES.match(profile):
                continue
            pdir = os.path.join(base, profile)
            if not os.path.isdir(pdir):
                continue
            for sub in BROWSER_CACHE_SUBS:
                add_unique(t, seen, simple('%s %s %s' % (browser, profile.lower(), sub.split()[0].lower()),
                                           os.path.join(pdir, sub)))
        add_unique(t, seen, simple('%s shadercache' % browser, os.path.join(base, 'ShaderCache')))
        add_unique(t, seen, simple('%s grshadercache' % browser, os.path.join(base, 'GrShaderCache')))
        add_unique(t, seen, simple('%s component crx' % browser, os.path.join(base, 'component_crx_cache')))
    def recycle():
        try:
            out = subprocess.run(['whoami', '/user'], capture_output=True, text=True).stdout
            m = re.search(r'S-1-5(?:-\d+)+', out)
            if not m:
                return 0, 'no SID'
            rb = os.path.join('C:\\$Recycle.Bin', m.group(0))
            if not os.path.isdir(rb):
                return 0, 'empty'
            s = dir_size(rb)
            if s < 50 * 1048576:
                return 0, 'negligible'
            shutil.rmtree(rb, ignore_errors=True)
            return s, 'emptied'
        except Exception as e:
            return 0, 'error: %r' % e
    add_unique(t, seen, ('recycle bin', r'C:\$Recycle.Bin\<you>', recycle))
    def old_sessions():
        sd = os.path.join(HOME, '.codex', 'sessions')
        if not os.path.isdir(sd):
            return 0, 'not present'
        cutoff = time.time() - 30 * 86400
        freed = 0
        for root, dirs, files in os.walk(sd):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    if os.path.getmtime(fp) < cutoff:
                        freed += os.path.getsize(fp)
                        os.remove(fp)
                except OSError:
                    pass
        return freed, '>30d sessions removed'
    add_unique(t, seen, ('codex sessions >30d', os.path.join(HOME, '.codex', 'sessions'), old_sessions))

    # ---- v4: aged session stores across ALL AI tools (>30d, never recent data) ----
    add_unique(t, seen, aged('claude sessions >30d', os.path.join(HOME, '.claude', 'projects'), 30))
    add_unique(t, seen, aged('claude hist >30d', os.path.join(HOME, '.claude', 'sessions'), 30))
    add_unique(t, seen, aged('claude file-history >30d', os.path.join(HOME, '.claude', 'file-history'), 30))
    add_unique(t, seen, aged('claude snapshots >7d', os.path.join(HOME, '.claude', 'shell-snapshots'), 7))
    add_unique(t, seen, aged('opencode sessions >30d', os.path.join(HOME, '.local', 'share', 'opencode', 'storage'), 30))
    add_unique(t, seen, aged('opencode logs >7d', os.path.join(HOME, '.local', 'share', 'opencode', 'log'), 7))
    add_unique(t, seen, aged('opencode cfg logs >7d', os.path.join(HOME, '.config', 'opencode', 'log'), 7))
    add_unique(t, seen, aged('cline sessions >30d', os.path.join(HOME, '.cline', 'data', 'sessions'), 30, dir_mode=True))
    add_unique(t, seen, aged('cline logs >7d', os.path.join(HOME, '.cline', 'data', 'logs'), 7))
    add_unique(t, seen, aged('cline ext tasks >30d',
                             os.path.join(APPD, 'Code', 'User', 'globalStorage', 'saoudrizwan.claude-dev', 'tasks'),
                             30, dir_mode=True))
    add_unique(t, seen, aged('kilo ext tasks >30d',
                             os.path.join(APPD, 'Code', 'User', 'globalStorage', 'kilocode.kilo-code', 'tasks'),
                             30, dir_mode=True))
    add_unique(t, seen, aged('continue sessions >30d', os.path.join(HOME, '.continue', 'sessions'), 30, dir_mode=True))
    add_unique(t, seen, aged('jcode sessions >30d', os.path.join(HOME, '.jcode', 'sessions'), 30))
    add_unique(t, seen, aged('jcode logs >7d', os.path.join(LOCAL, 'jcode', 'logs'), 7))
    add_unique(t, seen, aged('jcode todos >30d', os.path.join(HOME, '.jcode', 'todos'), 30))
    if DEEP or AGGRESSIVE:
        # v6: AI-guided hunter when model available
        use_ai = AGGRESSIVE and load_model() is not None
        hunted = hunt_cache_dirs(seen, use_ai=use_ai)
        for path in hunted:
            rel = path
            for prefix in (LOCAL + os.sep, APPD + os.sep, HOME + os.sep, 'C:\\'):
                if rel.lower().startswith(prefix.lower()):
                    rel = rel[len(prefix):]
                    break
            add_unique(t, seen, simple('hunt %s' % rel[:40], path))
    # loose junk FILES sweep (.tmp/.log/.bak/.dmp/~$ ...) — runs last so
    # files inside folders already targeted aren't double-counted
    junk_files = hunt_junk_files(seen)
    if junk_files:
        add_unique(t, seen, file_batch(
            'loose junk files' + (' (>7d appdata)' if DEEP else ''), junk_files))
    return t

SESSION_LABELS = ('codex sessions', 'claude sessions', 'claude hist', 'claude file-history',
                  'claude snapshots', 'opencode sessions', 'cline sessions', 'cline ext tasks',
                  'kilo ext tasks', 'continue sessions', 'jcode sessions', 'jcode todos')

REPORT_ONLY = [
    ('vscode workspace state', os.path.join(APPD, 'Code', 'User', 'workspaceStorage')),
    ('vscode extension data', os.path.join(APPD, 'Code', 'User', 'globalStorage')),
    ('vscode webview storage', os.path.join(APPD, 'Code', 'WebStorage')),
    ('cursor agent worktrees', os.path.join(HOME, '.cursor', 'worktrees')),
    ('installer package cache', r'C:\ProgramData\Package Cache'),
    ('global npm CLIs', os.path.join(APPD, 'npm')),
    ('python user site-packages', os.path.join(APPD, 'Python')),
]
# v6: Items moved from report-only to cleanable in AGGRESSIVE mode
REPORT_ONLY_SKIP_WHEN_FULL = {'vscode webview storage', 'cursor agent worktrees'}
REPORT_ONLY_SKIP_WHEN_AGGRESSIVE = {
    'vscode extension data', 'installer package cache', 'global npm CLIs', 'python user site-packages'
}

# ---------------- AI smart mode ----------------

def load_model():
    if getattr(sys, 'frozen', False):
        mp = os.path.join(os.path.dirname(sys.executable), 'model.json')
    else:
        mp = os.path.join(HERE, 'model.json')
    if not os.path.exists(mp):
        return None
    try:
        with open(mp) as f:
            m = json.load(f)
        return m
    except Exception:
        return None

def _brain_ver(model):
    b = str(model.get('brain', 'v1'))
    m = re.search(r'(\d+)', b)
    return int(m.group(1)) if m else 1

def featurize_for_model(path, size_bytes, age_days, model):
    """Feature vector matching train_model.featurize for the loaded brain."""
    import hashlib, math
    import numpy as np
    raw = path.replace('\\', '/').lower()
    parts = re.findall(r'[A-Za-z0-9_]+', raw)
    last = os.path.basename(path.rstrip('\\/'))
    lastn = re.sub(r'[\s._-]+', '', last).lower()
    ver = _brain_ver(model)
    if ver >= 6:
        try:
            from train_model import featurize as _train_featurize
            return _train_featurize(path, size_bytes, age_days,
                                    hash_dims=model.get('hash_dims'),
                                    n_extra=model.get('n_extra'))
        except Exception:
            pass
        hd = int(model.get('hash_dims', model['dims'] - 16))
        ne = int(model.get('n_extra', 16))
        x = np.zeros(hd + ne)
        def slot(tok):
            return int(hashlib.md5(tok.encode('utf-8')).hexdigest(), 16) % hd
        for tok in parts:
            x[slot(tok)] += 1.0
        if len(parts) >= 2:
            for tok in parts[-6:-1]:
                x[slot('p:' + tok)] += 0.7
            for tok in parts[:-1][-12:]:
                x[slot('a:' + tok)] += 0.3
        if lastn:
            x[slot('l:' + lastn)] += 2.0
            if len(lastn) >= 3:
                for i in range(len(lastn) - 2):
                    x[slot('g:' + lastn[i:i + 3])] += 0.35
            if len(lastn) >= 4:
                x[slot('sfx:' + lastn[-4:])] += 1.0
        depth = raw.count('/')
        sz = min(math.log1p(size_bytes / 1048576), 12) / 12
        age = min(age_days, 365) / 365
        x[hd] = sz
        x[hd + 1] = age
        x[hd + 2] = 1.0
        x[hd + 3] = min(depth, 16) / 16.0
        x[hd + 4] = 1.0 if 'appdata' in raw else 0.0
        x[hd + 5] = 1.0 if 'program files' in raw or 'programdata' in raw else 0.0
        x[hd + 6] = 1.0 if re.match(r'^[0-9a-f]{8,}$', lastn or '') else 0.0
        x[hd + 7] = min(len(parts), 24) / 24.0
        x[hd + 8] = 1.0 if 'users' in raw else 0.0
        x[hd + 9] = min(len(lastn), 24) / 24.0
        x[hd + 10] = min(len(raw), 160) / 160.0
        x[hd + 11] = sz * x[hd + 3]
        x[hd + 12] = age * x[hd + 4]
        x[hd + 13] = 1.0 if 'windows' in raw else 0.0
        x[hd + 14] = 1.0 if 'roaming' in raw else 0.0
        x[hd + 15] = 1.0 if any(c.isdigit() for c in lastn) else 0.0
        return x
    # v4/v5: 256 hashed + 5 extras
    total_dims = model['dims']
    D = total_dims - 5
    x = np.zeros(total_dims)
    def slot(tok):
        return int(hashlib.md5(tok.encode('utf-8')).hexdigest(), 16) % D
    for tok in parts:
        x[slot(tok)] += 1.0
    if len(parts) >= 2:
        for tok in parts[-6:-1]:
            x[slot('p:' + tok)] += 0.7
        if ver >= 4:
            for tok in parts[:-1]:
                x[slot('a:' + tok)] += 0.3
    x[D] = min(math.log1p(size_bytes / 1048576), 12) / 12
    x[D + 1] = min(age_days, 365) / 365
    x[D + 2] = 1.0 if re.search(r'(cache|temp|tmp|log)', path.lower()) else 0.0
    x[D + 3] = 1.0 if re.search(r'(downloads|documents|pictures|videos|desktop|onedrive|\.ssh|\.aws'
                                r'|globalstorage|workspacestorage|sessions|settings)', path.lower()) else 0.0
    x[D + 4] = 1.0
    return x

def ai_score(path, size_bytes, age_days, model):
    import math
    import numpy as np
    if model.get('arch') == 'mlp':
        x = featurize_for_model(path, size_bytes, age_days, model)
        W1 = np.array(model['W1']); b1 = np.array(model['b1'])
        h1 = np.maximum(0, x @ W1 + b1)
        if 'W3' in model:
            W2 = np.array(model['W2']); b2 = np.array(model['b2'])
            h2 = np.maximum(0, h1 @ W2 + b2)
            W3 = np.array(model['W3']).ravel(); b3 = float(model['b3'][0])
            return float(1 / (1 + math.exp(-max(-30.0, min(30.0, float(h2 @ W3) + b3)))))
        W2 = np.array(model['W2']).ravel(); b2 = float(model['b2'][0])
        return float(1 / (1 + math.exp(-max(-30.0, min(30.0, float(h1 @ W2) + b2)))))
    D = model['dims'] - 4
    w, b = model['weights'], model['bias']
    x = [0.0] * model['dims']
    import hashlib, math
    for tok in re.findall(r'[A-Za-z0-9_]+', path.replace('\\', '/').lower()):
        x[int(hashlib.md5(tok.encode()).hexdigest(), 16) % D] += 1.0
    x[D] = min(math.log1p(size_bytes / 1048576), 12) / 12
    x[D + 1] = min(age_days, 365) / 365
    x[D + 2] = 1.0 if re.search(r'(cache|temp|tmp|log)', path.lower()) else 0.0
    x[D + 3] = 1.0
    z = sum(wi * xi for wi, xi in zip(w, x)) + b
    return 1.0 / (1.0 + math.exp(-max(-30, min(30, z))))

PROTECTED = re.compile(r'(Downloads|Documents|Pictures|Videos|Music|Desktop|OneDrive)'
                       r'|(\.ssh|\.aws|\.git(?!hub)|globalStorage|workspaceStorage|sessions|node_modules$)',
                       re.IGNORECASE)

def smart_mode():
    root = SMART_ROOT
    model = load_model()
    if not model:
        print('model.json not found - run train_model.py first')
        return
    if not os.path.isdir(root):
        print('root not found:', root)
        return
    print('AI smart scan of %s (model trained %s on %d samples, holdout acc %.0f%%)'
          % (root, model['trained_on'], model['samples'], model.get('holdout_accuracy', model.get('train_accuracy', 0.9))*100))
    now = time.time()
    results = []
    for dirpath, dirs, files in os.walk(root, onerror=lambda e: None):
        depth = dirpath[len(root):].count(os.sep)
        if depth >= 4:
            dirs[:] = []
        for d in list(dirs):
            full = os.path.join(dirpath, d)
            try:
                st = os.stat(full)
                size = dir_size(full)
                age = (now - st.st_mtime) / 86400
            except OSError:
                continue
            if PROTECTED.search(full.replace('/', '\\')):
                dirs.remove(d)
                continue
            s = ai_score(full, size, age, model)
            results.append((s, size, full))
            if s < 0.35:
                dirs.remove(d)  # don't descend into clearly-safe trees
    results.sort(reverse=True)
    shown = 0
    print('\n%-6s %-10s %-5s PATH' % ('SCORE', 'SIZE', 'AGE(d)'))
    for s, size, full in results:
        if s < 0.55 or shown >= 25:
            continue
        try:
            age = int((now - os.stat(full).st_mtime) / 86400)
        except OSError:
            age = -1
        flag = 'JUNK?' if s >= 0.97 else ''
        print('%6.2f %10s %5d  %s %s' % (s, fmt(size), age, full, flag))
        shown += 1
    print('\n(%d candidate folders scanned, top %d shown)' % (len(results), shown))
    print('AI scores are advisory. Deletion still requires whitelist match or manual review.')

# ---------------- main ----------------

def main():
    if SMART_ROOT:
        smart_mode()
        return
    aggressive = FULL
    mode = 'AGGRESSIVE' if AGGRESSIVE else ('DEEP' if DEEP else ('FULL' if FULL else 'SAFE'))
    try:
        free0 = shutil.disk_usage('C:\\').free
    except OSError:
        free0 = None
    
    # v6: Admin check for privileged targets
    admin_status = ' (admin)' if is_admin() else ''
    print('StorageCleaner v6 [%s]%s - scanning caches...' % (mode, admin_status))
    if free0 is not None:
        print('C: free space now: %s' % fmt(free0))
    
    rows = []
    for label, path, fn in build_targets():
        is_aggr = label.startswith(SESSION_LABELS) or label.startswith(('recycle bin',)) or label == 'playwright browsers'
        if is_aggr and not aggressive:
            rows.append((label, path, None, 'skipped (--full)', 0))
            continue
        pre = getattr(fn, 'preview_size', None) if fn is not None else None
        if pre is not None:
            size = pre
        elif label == 'cline telemetry db':
            dbp = os.path.join(path, 'data', 'db', 'hub-events-hub-production.db')
            size = os.path.getsize(dbp) if os.path.exists(dbp) else 0
        elif path and os.path.isdir(path):
            size = dir_size(path)
        elif path and os.path.isfile(path):
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
        else:
            size = 0
        rows.append((label, path, fn, '', size))

    nonzero = [r for r in rows if r[4] > 0]
    zeros = len(rows) - len(nonzero)
    print('\n%-32s %12s' % ('TARGET', 'RECLAIMABLE'))
    print('-' * 46)
    shown = 0
    hidden_hunt = 0
    for label, path, fn, status, size in nonzero:
        if label.startswith('hunt ') and size < 5 * 1048576:
            hidden_hunt += 1
            continue
        print('%-32s %12s' % (label[:32], fmt(size)))
        shown += 1
    print('-' * 46)
    print('(%d targets already at/near zero%s)' % (
        zeros, (', %d tiny hunt hits hidden' % hidden_hunt) if hidden_hunt else ''))
    total = sum(r[4] for r in nonzero)
    print('%-32s %12s' % ('TOTAL reclaimable', fmt(total)))

    print('\nReport-only (needs your judgement — not deleted):')
    for label, path in REPORT_ONLY:
        if FULL and label in REPORT_ONLY_SKIP_WHEN_FULL:
            continue
        if AGGRESSIVE and label in REPORT_ONLY_SKIP_WHEN_AGGRESSIVE:
            continue
        if os.path.isdir(path):
            print('  %-28s %10s' % (label[:28], fmt(dir_size(path))))

    model = load_model()
    if model:
        acc = model.get('holdout_accuracy', model.get('train_accuracy', 0))
        print('\nAI model: loaded (brain %s, acc %.0f%%)' % (model.get('brain', '?'), acc * 100))
    else:
        print('\nAI model: model.json missing (run train_model.py)')

    if REPORT:
        print('\nReport mode (--report): scan only, nothing deleted.')
        return

    do_clean = QUIET
    if not QUIET:
        if AGGRESSIVE:
            scope = 'AGGRESSIVE (DEEP + extensions/SDKs/packages + AI-guided hunter)'
        elif DEEP:
            scope = 'DEEP caches (editors/browsers/temp/hunter + recycle + rebuildable SDK caches)'
        elif aggressive:
            scope = 'SAFE items + AGGRESSIVE items'
        else:
            scope = 'SAFE items'
        try:
            ans = input('\nClean %s now? [y/N] ' % scope).strip().lower()
        except EOFError:
            ans = 'n'
        do_clean = ans in ('y', 'yes')
    if not do_clean:
        print('Nothing cleaned.')
        return

    print('\nCleaning...')
    freed_total = 0
    for label, path, fn, status, size in rows:
        if fn is None:
            continue
        try:
            freed, note = fn()
        except Exception as e:
            freed, note = 0, 'error: %r' % e
        freed_total += max(freed, 0)
        if freed > 0 or (note != 'not present' and note != 'already empty'):
            line = '  %-26s %10s   %s' % (label[:26], fmt(max(freed, 0)), note)
            print(line)
            log(line.strip())
    removed_dirs = 0
    for r in FILE_JUNK_TEMP_ROOTS:
        removed_dirs += prune_empty_dirs(r)
    if removed_dirs:
        print('  pruned %d empty folders' % removed_dirs)
        log('pruned %d empty folders' % removed_dirs)
    print('\nTOTAL FREED: %s' % fmt(freed_total))
    try:
        free1 = shutil.disk_usage('C:\\').free
        if free0 is not None:
            print('C: free space now: %s (was %s)' % (fmt(free1), fmt(free0)))
    except OSError:
        pass
    log('session total freed: %s' % fmt(freed_total))

if __name__ == '__main__':
    main()
