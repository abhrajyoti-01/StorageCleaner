#!/usr/bin/env python3
"""StorageCleaner v9.1 - Advanced AI-assisted disk cleanup.
Covers: AI CLI tools, editor/browser caches, dev package caches, Windows
delivery caches, loose junk files (.tmp/.log/.bak/.dmp), crash dumps,
Electron app caches, plus a bounded AppData cache discovery pass. Pure
stdlib; optional trained model in model.json (brain v9+).

v9 changes (safety, coverage, speed):
  - safety_veto(): a hard layer that runs BEFORE the model and before name
    matching. Anything it rejects is never deleted, whatever the model says.
    Closes the v8 failure where Recent/Themes/ConnectedDevicesPlatform were
    scored >= 0.85 and would have been removed.
  - Discovery now runs in SAFE mode too (bounded, depth 3, name patterns),
    so new app caches are found without --deep.
  - dir_size() on os.scandir (no per-entry symlink lstat); model weights
    parsed once per process; target sizing across a thread pool; report-only
    folders measured only under --report.
  - --explain PATH prints the score plus which rule or veto fired.

v9.1 changes (old Windows files, slow-boot diagnosis):
  - DEEP: privileged removal of Windows.old, $Windows.~BT, $Windows.~WS,
    $GetCurrent, $SysReset, $WinREAgent (10-40 GB update leftovers; admin
    only; ends the update rollback window) + Windows\Logs aged >30d.
  - --performance: power scheme, battery CPU boost mode, fast startup,
    startup programs, disk headroom - the real boot-speed causes.
  - --fix-power: re-enables CPU boost on battery. "Fast on charger, slow on
    battery" is power throttling, not junk; cleaning cannot fix it.
  - C:\Windows\Prefetch is deliberately NOT cleaned: deleting it makes the
    NEXT boots slower while Windows rebuilds it.

Usage:
  python StorageCleaner.py                report + interactive prompt (safe)
  python StorageCleaner.py -q             clean SAFE items without asking
  python StorageCleaner.py --full         also recycle bin, old sessions, playwright
  python StorageCleaner.py --deep         advanced: deeper hunter + extra caches + --full
  python StorageCleaner.py --aggressive   DEEP + report-only items (extensions, sdk)
  python StorageCleaner.py --smart DIR    AI-score every folder under DIR (report)
  python StorageCleaner.py --explain PATH why is this path (not) considered junk
  python StorageCleaner.py --performance  power/startup/disk report: why boot is slow
  python StorageCleaner.py --fix-power    re-enable full CPU speed on battery (admin)
Safe by veto + whitelist: never touches Downloads/Documents/Pictures/Videos/
Desktop/OneDrive, browser profiles, cookies, or app state folders.
"""
import os, sys, shutil, sqlite3, subprocess, time, json, re, ctypes, winreg
from concurrent.futures import ThreadPoolExecutor

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
PERFORMANCE = '--performance' in sys.argv
FIX_POWER = '--fix-power' in sys.argv

def argv_value(flag):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None
SMART_ROOT = argv_value('--smart')
EXPLAIN_PATH = argv_value('--explain')
SIZE_WORKERS = 16

def log(msg):
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%dT%H:%M:%S') + ' ' + msg + '\n')
    except OSError:
        pass

def dir_size(path):
    """Recursive byte total. os.scandir + cached DirEntry stats: os.walk lstats
    every entry to test for symlinks, which is ~4x slower on Windows."""
    total = 0
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            it = os.scandir(cur)
        except OSError:
            continue
        with it:
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    else:
                        total += entry.stat(follow_symlinks=False).st_size
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

# ---------------- safety veto ----------------
# Runs BEFORE the model and BEFORE name matching. A vetoed path is never
# deleted, whatever the brain or a name pattern says. This is the layer that
# makes a badly trained model annoying instead of destructive: the model can
# only *promote* a candidate that already passed the veto, never override it.

# Protected user data. Anchored to the real profile so that an app's own
# "downloads" scratch folder (.claude\downloads) is not mistaken for the
# user's Downloads. OneDrive is matched as a profile-level folder, not any
# component named OneDrive (AppData\Local\Microsoft\OneDrive\logs is a log dir).
PROTECTED_USER_DIRS = ('Downloads', 'Documents', 'Pictures', 'Videos', 'Music',
                       'Desktop', 'OneDrive')
VETO_ROOTS = re.compile(
    r'^(?:' + re.escape(HOME) + r'|' + re.escape(HOME) + r'[\\/]OneDrive)'
    r'[\\/](?:' + '|'.join(PROTECTED_USER_DIRS) + r')(?:[\\/]|$)'
    r'|(?:^|[\\/])\.(?:ssh|aws|gnupg)(?:[\\/]|$)',
    re.I)

# installed applications and packaged-app state, never bulk-deleted
VETO_SUBTREES = re.compile(
    r'\\AppData\\Local\\Programs(\\|$)'
    r'|\\AppData\\Local\\Packages(\\|$)', re.I)

# final path component that means "this folder is state, not scratch"
VETO_NAMES = {
    # user-visible state
    'recent', 'themes', 'signatures', 'templates',
    'localstate', 'roaming', 'settings', 'config', 'configs', 'preferences',
    'user', 'profile', 'profiles', 'default', 'network',
    # code and libraries
    'bin', 'lib', 'libs', 'src', 'source', 'include', 'assets',
    'extensions', 'plugins', 'skills', 'commands', 'agents',
    # tool and editor state (age-managed elsewhere, never bulk-deleted)
    'globalstorage', 'workspacestorage', 'sessions', 'session', 'tasks',
    'projects', 'history', 'todos', 'memory', 'prompts', 'keybindings',
    # browser profile state
    'cookies', 'login data', 'web data', 'local storage', 'session storage',
    'indexeddb', 'databases', 'bookmarks', 'secure preferences',
    # credentials and secrets
    'credentials', 'secrets', 'tokens', 'keys',
}

# A folder whose own name is unambiguously scratch is exempt from the content
# check below (a cache may legitimately contain a .db or .json manifest).
STRONG_CACHE_NAME = re.compile(
    r'^(?:cache|caches|cached\w*|gpucache|code cache|shadercache|grshadercache|'
    r'graphitedawncache|dawn\w*cache|crashpad|crashdumps?|logs?|temp|tmp|'
    r'htmlcache|browsercache|inetcache|dxcache|glcache|d3dscache|thumbcache|'
    r'iconcache|deliveryoptimization|blobcache|tooloutput|paste-cache|'
    r'cache_data|no_vary_search|webstorage|component_crx_cache)$', re.I)

# a top-level file like this means the folder holds real state
VETO_STATE_EXTS = {
    '.db', '.sqlite', '.sqlite3', '.json', '.toml', '.ini', '.cfg',
    '.exe', '.dll', '.img', '.jar', '.theme', '.lnk', '.cdp', '.sst',
    '.pfx', '.pem', '.key', '.crt', '.vhd', '.vhdx',
}
VETO_STATE_NAMES = re.compile(
    r'^(?:cookies|login data|web data|bookmarks|preferences|secure preferences|'
    r'local state|history|favicons|shortcuts|top sites|first party sets)$', re.I)

VETOED = []  # (label, path, reason) collected during build_targets

# v9.1: well-known Windows update/reset leftovers, deletable only through the
# explicit DEEP-tier privileged targets. The generic content check would veto
# some of these ($WinREAgent keeps .ini at top level), so they are exempted
# here by exact path. The discovery hunter can never reach them (its roots
# never include C:\ root), so this allowlist cannot leak into discovery.
SYSTEM_CLEANUP_PATHS = frozenset(p.lower() for p in (
    r'C:\Windows.old',
    r'C:\$Windows.~BT',
    r'C:\$Windows.~WS',
    r'C:\$GetCurrent',
    r'C:\$SysReset',
    r'C:\$WinREAgent',
))


def safety_veto(path, whole_dir=True):
    """Return (vetoed, reason). whole_dir=False is for age-based sweeps that
    only remove old files and never the folder itself, so only the root and
    subtree rules apply to them."""
    if not path:
        return True, 'no path'
    p = path.replace('/', '\\')
    if p.lower() in SYSTEM_CLEANUP_PATHS:
        return False, 'known system cleanup path'
    m = VETO_ROOTS.search(p)
    if m:
        return True, 'protected user data: %s' % m.group(0)
    if VETO_SUBTREES.search(p):
        return True, 'installed app / packaged app state'
    if not whole_dir:
        return False, 'no veto'
    last = os.path.basename(p.rstrip('\\'))
    ln = last.lower().lstrip('.')
    if ln in VETO_NAMES:
        return True, 'state folder: %s' % last
    if STRONG_CACHE_NAME.match(ln):
        return False, 'strong cache name: %s' % last
    # Content check: a state-shaped FILE at the top level means real data.
    # Directories never count - a NuGet-style package folder named like a
    # file (microsoft.data.sqlite) is a package, not a state file.
    try:
        with os.scandir(p) as it:
            for entry in it:
                if not entry.is_file(follow_symlinks=False):
                    continue
                low = entry.name.lower()
                if VETO_STATE_NAMES.match(low):
                    return True, 'state file: %s' % entry.name
                if os.path.splitext(low)[1] in VETO_STATE_EXTS:
                    return True, 'state file: %s' % entry.name
    except OSError:
        pass
    return False, 'no veto'


def walk_blocked(path):
    """Should the discovery walk refuse to descend here?

    Only protected roots and installed-app subtrees. A folder can be vetoed as a
    deletion target and still contain cache children worth finding (e.g.
    Epic Games\EOSOverlay holds a state file but also BrowserCache), so the
    content and state-name checks must not prune traversal.
    """
    if not path:
        return True
    p = path.replace('/', '\\')
    return bool(VETO_ROOTS.search(p) or VETO_SUBTREES.search(p))


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
        cur.close()
        con.isolation_level = None
        con.execute('VACUUM')
        con.close()
        return before - os.path.getsize(db), 'pruned to %d events' % kept
    except Exception as e:
        return 0, 'error: %r' % e

t_cline_db.whole_dir = False  # prunes rows in a db, never deletes the folder

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
    fn.aged = True
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
    fn.whole_dir = True
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
    fn.whole_dir = True
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
    fn.whole_dir = False  # deletes only files matching the pattern
    return label, path, fn

def privileged_delete(label, path, pattern=None, whole_dir=False):
    """Delete protected system files (e.g., MEMORY.DMP) with takeown + icacls if admin.

    whole_dir: path itself is a protected directory to remove entirely
    (e.g. C:\\Windows.old, owned by TrustedInstaller). Ownership is taken
    recursively, then the tree is granted to the Administrators group (by SID,
    so it works on any Windows display language) and deleted."""
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
        elif os.path.isdir(path) and whole_dir:
            targets = [path]

        for target in targets:
            try:
                recursive = os.path.isdir(target) and whole_dir
                sz = os.path.getsize(target) if os.path.isfile(target) else dir_size(target)
                # Take ownership then delete. Recursive takeown on a big tree
                # (Windows.old can hold 200k+ files) needs a long timeout.
                if recursive:
                    subprocess.run(['takeown', '/F', target, '/R', '/A', '/D', 'Y'],
                                   capture_output=True, timeout=600)
                    subprocess.run(['icacls', target, '/grant', '*S-1-5-32-544:F', '/T'],
                                   capture_output=True, timeout=600)
                else:
                    subprocess.run(['takeown', '/F', target, '/A'],
                                   capture_output=True, timeout=10)
                    subprocess.run(['icacls', target, '/grant', '*S-1-5-32-544:F'],
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
    if whole_dir:
        fn.whole_dir = True  # the folder itself goes away, not just its contents
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
    r'(^|[/\\\s._-])(caches?|cached\w*|gpucache|codecache|shadercache|'
    r'crashpad|crashdumps?|temp|tmp|webview|dawncache|'
    r'deliveryoptimization|thumbcache|iconcache|vsix)([/\\\s._-]|$)',
    re.I)

# v9: token/suffix matcher. The regex above needs a separator on both sides, so
# it misses "Code Cache" (space) and "SharedClientCache" (suffix). Those are
# exactly the families that were invisible to safe mode.
CACHE_TOKENS = {
    'cache', 'caches', 'cached', 'tmp', 'temp', 'log', 'logs',
    'crashpad', 'crashdump', 'crashdumps', 'webcache', 'htmlcache',
    'browsercache', 'inetcache', 'tooloutput', 'blobcache', 'packetcache',
    'shadercache', 'gpucache', 'codecache', 'thumbcache', 'iconcache',
}
CACHE_SUFFIXES = ('cache', 'caches', 'cached', 'crashpad', 'crashdumps',
                  'crashdump')


def cache_name_match(name):
    """True when a folder name is unambiguously scratch space."""
    low = name.lower()
    n = re.sub(r'[^a-z0-9]', '', low)
    if not n:
        return False
    if n in CACHE_TOKENS:
        return True
    if n.endswith(CACHE_SUFFIXES):
        return True
    for tok in re.split(r'[^a-z0-9]+', low):
        if tok in CACHE_TOKENS:
            return True
    return False
HUNTER_SKIP = re.compile(
    r'(Downloads|Documents|Pictures|Videos|Music|Desktop|OneDrive|'
    # site-packages (pip/uv/venv, any layout): installed packages live there
    # and some are literally named like caches (propcache, diskcache); the
    # bytecode caches inside regenerate anyway, so there is nothing to win.
    r'\\Local\\Microsoft\\Windows\\INetCookies|'
    r'\\Local\\Microsoft\\Credentials|'
    r'\\.ssh|\\.aws|\\.gnupg|globalStorage|workspaceStorage|'
    r'\\node_modules($|\\)|\\Packages($|\\)|\\Local\\Programs($|\\)|'
    r'\\Local\\wsl($|\\)|GeForce NOW|'
    r'\\Windows\\WinSxS|\\Windows\\Installer|\\Windows\\System32|'
    r'\\WindowsApps|'
    r'\\site-packages($|\\))',
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

    v9: runs in every mode (bounded in SAFE), and every candidate must pass
    safety_veto() before it is accepted. The model can only promote a candidate
    that already passed the veto; it can never override it.
    """
    found = []
    found_norm = set()
    model = load_model() if use_ai else None

    # v9: SAFE mode gets a shallow, name-only pass so new app caches are found
    max_depth = 8 if AGGRESSIVE else (5 if DEEP else 3)
    roots = HUNTER_ROOTS_AGGRESSIVE if AGGRESSIVE else (HUNTER_ROOTS_DEEP if DEEP else HUNTER_ROOTS)
    limit = 500 if AGGRESSIVE else 300

    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirs, _files in os.walk(root, onerror=lambda e: None):
            if len(found) >= limit:
                return found
            depth = dirpath[len(root):].count(os.sep)
            if depth > max_depth:
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
                # v9: never descend into protected user data or installed apps
                if walk_blocked(full):
                    continue

                # Name-based match (fast path)
                if cache_name_match(d):
                    if safety_veto(full)[0]:
                        keep.append(d)
                        continue
                    found.append(full)
                    found_norm.add(nfull)
                    continue

                # AI scoring (only with a model, and only in AGGRESSIVE mode)
                if model and AGGRESSIVE:
                    try:
                        age = (time.time() - os.stat(full).st_mtime) / 86400
                        if ai_score(full, 0, age, model) >= 0.85 and not safety_veto(full)[0]:
                            found.append(full)
                            found_norm.add(nfull)
                            continue
                    except OSError:
                        pass

                keep.append(d)
            # Names are checked at the boundary level even when we stop there,
            # so a cache at exactly max_depth is still seen (Code Cache under
            # Partitions\vscode-browser sits at depth 4).
            dirs[:] = keep if depth < max_depth else []
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
    fn.whole_dir = False
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
    label, path, fn = item
    whole = getattr(fn, 'whole_dir', None)
    if whole is None:
        whole = not getattr(fn, 'aged', False)
    vetoed, reason = safety_veto(path, whole_dir=whole)
    if vetoed:
        VETOED.append((label, path, reason))
        log('veto: %s (%s) - %s' % (label, path, reason))
        return
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
        # v9.1: old Windows / setup leftovers (often 10-40 GB after a feature
        # update). Removing Windows.old ends the rollback window for that
        # update - which is why these live in DEEP, not SAFE. Admin-only;
        # without elevation they are sized in the report and skipped.
        add_unique(t, seen, privileged_delete('old windows (windows.old)', r'C:\Windows.old', whole_dir=True))
        add_unique(t, seen, privileged_delete('setup leftover (~bt)', r'C:\$Windows.~BT', whole_dir=True))
        add_unique(t, seen, privileged_delete('setup leftover (~ws)', r'C:\$Windows.~WS', whole_dir=True))
        add_unique(t, seen, privileged_delete('setup leftover (getcurrent)', r'C:\$GetCurrent', whole_dir=True))
        add_unique(t, seen, privileged_delete('reset leftover (sysreset)', r'C:\$SysReset', whole_dir=True))
        add_unique(t, seen, privileged_delete('winre update leftover', r'C:\$WinREAgent', whole_dir=True))
        # v9.1: CBS/DISM/WindowsUpdate logs, files older than 30 days only
        add_unique(t, seen, aged('windows update logs', r'C:\Windows\Logs', 30))
    
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
    old_sessions.whole_dir = False  # ages files out, never deletes the folder
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
    else:
        # v9: bounded name-only discovery in SAFE mode. Without this, safe mode
        # could only see the 532 hardcoded paths and missed every new app cache.
        for path in hunt_cache_dirs(seen, use_ai=False):
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

_MODEL_CACHE = []


def load_model():
    if _MODEL_CACHE:
        return _MODEL_CACHE[0]
    if getattr(sys, 'frozen', False):
        mp = os.path.join(os.path.dirname(sys.executable), 'model.json')
    else:
        mp = os.path.join(HERE, 'model.json')
    m = None
    if os.path.exists(mp):
        try:
            with open(mp) as f:
                m = json.load(f)
        except Exception:
            m = None
    _MODEL_CACHE.append(m)
    return m

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

_WEIGHT_CACHE = {}


def _weights(model):
    """Parse the JSON weight lists into ndarrays once per process. v8 rebuilt
    them on every ai_score() call, which the hunter calls per candidate dir."""
    key = id(model)
    w = _WEIGHT_CACHE.get(key)
    if w is None:
        import numpy as np
        w = {'W1': np.array(model['W1']), 'b1': np.array(model['b1']),
             'W2': np.array(model['W2']), 'b2': np.array(model['b2'])}
        if 'W3' in model:
            w['W3'] = np.array(model['W3']).ravel()
            w['b3'] = float(model['b3'][0])
        _WEIGHT_CACHE[key] = w
    return w


def ai_score(path, size_bytes, age_days, model):
    import math
    import numpy as np
    if model.get('arch') == 'mlp':
        x = featurize_for_model(path, size_bytes, age_days, model)
        w = _weights(model)
        h1 = np.maximum(0, x @ w['W1'] + w['b1'])
        if 'W3' in w:
            h2 = np.maximum(0, h1 @ w['W2'] + w['b2'])
            return float(1 / (1 + math.exp(-max(-30.0, min(30.0, float(h2 @ w['W3']) + w['b3'])))))
        return float(1 / (1 + math.exp(-max(-30.0, min(30.0, float(h1 @ w['W2'].ravel()) + float(w['b2'][0]))))))
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
    print('AI smart scan of %s (brain %s, trained %s on %d samples, holdout acc %.0f%%)'
          % (root, model.get('brain', '?'), model['trained_on'], model['samples'],
             model.get('holdout_accuracy', model.get('train_accuracy', 0.9)) * 100))
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
            if PROTECTED.search(full.replace('/', '\\')) or safety_veto(full)[0]:
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

def measure(rows):
    """Size every target. Directory walks are I/O bound, so a small thread pool
    cuts wall time on the handful of huge targets (gradle, uv, npm, Temp)."""
    def size_of(row):
        label, path, fn = row[0], row[1], row[2]
        pre = getattr(fn, 'preview_size', None) if fn is not None else None
        if pre is not None:
            return pre
        if label == 'cline telemetry db':
            dbp = os.path.join(path, 'data', 'db', 'hub-events-hub-production.db')
            return os.path.getsize(dbp) if os.path.exists(dbp) else 0
        if path and os.path.isdir(path):
            return dir_size(path)
        if path and os.path.isfile(path):
            try:
                return os.path.getsize(path)
            except OSError:
                return 0
        return 0

    if not rows:
        return []
    with ThreadPoolExecutor(max_workers=SIZE_WORKERS) as ex:
        sizes = list(ex.map(size_of, rows))
    return [(r[0], r[1], r[2], '', s) for r, s in zip(rows, sizes)]


def explain_mode():
    """Print why a path is or is not considered junk."""
    p = EXPLAIN_PATH
    print('explain: %s' % p)
    print('  exists : %s' % os.path.exists(p))
    if not os.path.isdir(p):
        print('  not a directory - nothing to score')
        return
    vetoed, reason = safety_veto(p)
    print('  veto   : %s (%s)' % ('VETOED' if vetoed else 'passed', reason))
    print('  name   : cache_name_match=%s' % cache_name_match(os.path.basename(p.rstrip('\\/'))))
    try:
        size = dir_size(p)
        age = (time.time() - os.stat(p).st_mtime) / 86400
    except OSError as e:
        print('  stat   : error %r' % e)
        return
    print('  size   : %s' % fmt(size))
    print('  age    : %.0f days' % age)
    model = load_model()
    if not model:
        print('  model  : model.json missing')
        return
    score = ai_score(p, size, age, model)
    print('  score  : %.3f (brain %s)' % (score, model.get('brain', '?')))
    print('  verdict: %s' % ('would be deleted' if (not vetoed and score >= 0.85)
                             else 'kept' if vetoed else 'kept (below 0.85)'))


# ---------------- main ----------------

# ---------------- performance / power mode (v9.1) ----------------
# Slow boot on battery (fast while charging) is Windows power throttling on
# DC, not junk files: CPU boost and the power-mode overlay get clamped the
# moment the charger is unplugged. Cleaning cannot fix that. These two modes
# report the real state and re-enable full speed on battery.

OVERLAY_NAMES = {
    '961cc777-2547-4f9d-8174-7d86181b8a7a': 'Best battery (heaviest throttle)',
    '00000000-0000-0000-0000-000000000000': 'Balanced',
    'ded574b5-45a0-4f42-8737-46345c09c238': 'Best performance',
}
BOOST_MODES = {
    0: 'Disabled - CPU stuck at base clock (the battery slowdown)',
    1: 'Enabled',
    2: 'Aggressive',
    3: 'Efficient enabled',
    4: 'Efficient aggressive',
}
BALANCED_OVERLAY = '00000000-0000-0000-0000-000000000000'


def _run(cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ''


def parse_power_indexes(text):
    """Pull the AC and DC setting indexes out of `powercfg /q` output."""
    ac = dc = None
    for line in text.splitlines():
        low = line.strip().lower()
        m = re.search(r'ac power setting index\s*:\s*(0x[0-9a-f]+)', low)
        if m:
            ac = int(m.group(1), 16)
        m = re.search(r'dc power setting index\s*:\s*(0x[0-9a-f]+)', low)
        if m:
            dc = int(m.group(1), 16)
    return ac, dc


def boost_mode_state():
    """(ac, dc) CPU boost mode of the current scheme, or (None, None) when
    the setting is unreadable (needs admin / unsupported processor)."""
    out = _run(['powercfg', '/q', 'SCHEME_CURRENT', 'SUB_PROCESSOR', 'PERFBOOSTMODE'])
    if not out or 'power setting index' not in out.lower():
        return None, None
    return parse_power_indexes(out)


def on_battery():
    class POWERSTATUS(ctypes.Structure):
        _fields_ = [('ACLineStatus', ctypes.c_byte), ('BatteryFlag', ctypes.c_byte),
                    ('BatteryLifePercent', ctypes.c_byte), ('Reserved1', ctypes.c_byte),
                    ('BatteryLifeTime', ctypes.c_ulong), ('BatteryFullLifeTime', ctypes.c_ulong)]
    ps = POWERSTATUS()
    try:
        ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(ps))
    except Exception:
        return False
    return ps.ACLineStatus == 0


def fast_startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r'SYSTEM\CurrentControlSet\Control\Session Manager\Power') as k:
            val, _ = winreg.QueryValueEx(k, 'HiberbootEnabled')
            return bool(val)
    except OSError:
        return None


def _startup_approved():
    """{entry name: enabled} from Explorer's StartupApproved blobs.
    Byte 0: 02/06 = enabled, 03 = disabled."""
    approved = {}
    for hive, path in (
        (winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'),
        (winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder'),
        (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run'),
        (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder'),
    ):
        try:
            with winreg.OpenKey(hive, path) as k:
                for i in range(winreg.QueryInfoKey(k)[1]):
                    name, val, _ = winreg.EnumValue(k, i)
                    if isinstance(val, bytes) and val:
                        approved[name] = val[0] not in (3, 7)
        except OSError:
            pass
    return approved


def startup_items():
    """(name, source, enabled) for every autostart entry. enabled is None when
    Windows never recorded an on/off decision for it."""
    approved = _startup_approved()
    items = []
    for src_label, hive, path in (
        ('HKCU Run', winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run'),
        ('HKCU RunOnce', winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\RunOnce'),
        ('HKLM Run', winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Windows\CurrentVersion\Run'),
        ('HKLM Run (32-bit)', winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run'),
    ):
        try:
            with winreg.OpenKey(hive, path) as k:
                for i in range(winreg.QueryInfoKey(k)[1]):
                    name, _cmd, _ = winreg.EnumValue(k, i)
                    items.append((name, src_label, approved.get(name)))
        except OSError:
            pass
    program_data = os.environ.get('ProgramData', r'C:\ProgramData')
    for src_label, folder in (
        ('Startup folder (you)', os.path.join(APPD, 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')),
        ('Startup folder (all users)', os.path.join(program_data, 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'StartUp')),
    ):
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            if name.lower().endswith('.lnk'):
                items.append((name[:-4], src_label, approved.get(name)))
    return items


def performance_report():
    print('StorageCleaner v9.1 performance report')
    print('=' * 62)
    print('Why is this PC slow, especially on battery? Real causes, not guesses.')

    out = _run(['powercfg', '/getactivescheme'])
    m = re.search(r'GUID:\s*[0-9a-f-]+\s*\((.+)\)', out)
    print('\nPower scheme          : %s' % (m.group(1).strip() if m else 'unknown'))
    print('Running on            : %s' % ('battery' if on_battery() else 'charger (AC)'))

    out = _run(['powercfg', '/overlaygetactivescheme'])
    m = re.search(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', out)
    if m:
        print('Power mode (overlay)  : %s' % OVERLAY_NAMES.get(m.group(1), m.group(1)))
    else:
        print('Power mode (overlay)  : not used on this system')

    ac, dc = boost_mode_state()
    boost_problem = dc == 0
    if ac is None and dc is None:
        print('CPU boost (AC/battery): not readable without admin')
    else:
        print('CPU boost on charger  : %s' % (BOOST_MODES.get(ac, ac) if ac is not None else 'unknown'))
        print('CPU boost on battery  : %s' % (BOOST_MODES.get(dc, dc) if dc is not None else 'unknown'))

    fs = fast_startup_enabled()
    print('Fast startup (boot)   : %s' % ('enabled' if fs else 'disabled' if fs is not None else 'unknown'))

    items = startup_items()
    enabled_count = sum(1 for i in items if i[2] is not False)
    print('\nStartup programs: %d enabled, %d disabled in total' % (enabled_count, len(items) - enabled_count))
    for name, src, en in items:
        print('  [%s] %-30.30s  (%s)' % ('on ' if en is not False else 'off', name, src))
    print('  ^ each enabled one adds to every boot and logon.')
    print('    Disable what you do not need: Task Manager > Startup apps.')

    try:
        u = shutil.disk_usage('C:\\')
        pct = u.free / u.total * 100
        warn = '  <- LOW, Windows slows down badly under 15%' if pct < 15 else ''
        print('\nC: free space: %s of %s (%.0f%%)%s' % (fmt(u.free), fmt(u.total), pct, warn))
    except OSError:
        pass

    print('\nWhat to do about slow boot ON BATTERY (in order):')
    if boost_problem:
        print('  1. CPU boost is DISABLED on battery. Windows clamps the CPU to its')
        print('     base clock whenever unplugged - this is the classic "fast when')
        print('     charging, slow on battery" symptom. Fix in one command:')
        print('       python StorageCleaner.py --fix-power')
    elif dc is None:
        print('  1. Battery CPU boost mode could not be read. Run --fix-power from an')
        print('     administrator terminal to see and set it.')
    else:
        print('  1. CPU boost on battery is already enabled - not the problem.')
    print('  2. Startup programs above: the biggest controllable boot cost.')
    if fs is False:
        print('  3. Fast startup is disabled. Enabling it shortens boot:')
        print('     admin: powercfg /hibernate on  &&  reg add "HKLM\\SYSTEM\\CurrentControlSet\\'
              'Control\\Session Manager\\Power" /v HiberbootEnabled /t REG_DWORD /d 1 /f')
    print('\nHonest note: deleting caches/junk frees disk, it does NOT change')
    print('battery boot speed. On battery the cause is power throttling (above).')


def fix_power():
    """Re-enable full CPU speed on battery. Needs admin; self-elevates."""
    if not is_admin():
        script = os.path.abspath(__file__)
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, 'runas', sys.executable, '"%s" --fix-power' % script, None, 1)
        if ret > 32:
            print('Asking for administrator approval (UAC) to change power settings...')
        else:
            print('Could not elevate. Right-click your terminal and "Run as administrator",')
            print('then run: python StorageCleaner.py --fix-power')
        return

    ac0, dc0 = boost_mode_state()

    def boost_txt(v):
        return BOOST_MODES.get(v, hex(v) if v is not None else 'unreadable')

    print('Before: CPU boost charger=%s | battery=%s' % (boost_txt(ac0), boost_txt(dc0)))

    # 1. Boost mode 2 (Aggressive) on battery for the current scheme.
    _run(['powercfg', '/setdcvalueindex', 'SCHEME_CURRENT', 'SUB_PROCESSOR',
          'PERFBOOSTMODE', '2'])
    # 2. Re-apply the scheme so the value takes effect immediately.
    _run(['powercfg', '/setactive', 'SCHEME_CURRENT'])
    print('Set    : battery CPU boost -> 2 (Aggressive)')

    # 3. The power-mode overlay (Best battery / Balanced / Best performance)
    #    is remembered per power source and only settable while ON that
    #    source. If we are on battery right now, move it off heavy throttle.
    if on_battery():
        _run(['powercfg', '/overlaysetactive', BALANCED_OVERLAY])
        print('Set    : battery power mode -> Balanced')
    else:
        print('Note   : you are on the charger. Run --fix-power once more while')
        print('         ON BATTERY to also set the battery power mode to Balanced.')

    ac1, dc1 = boost_mode_state()
    print('After : CPU boost charger=%s | battery=%s' % (boost_txt(ac1), boost_txt(dc1)))
    if dc1 is None:
        print('Could not verify - this processor/driver may not expose PERFBOOSTMODE.')
    elif dc1 == dc0 == 2:
        print('Battery boost was already enabled - battery slowness has another cause')
        print('(check startup programs above with --performance).')


def main():
    if FIX_POWER:
        fix_power()
        return
    if PERFORMANCE:
        performance_report()
        return
    if SMART_ROOT:
        smart_mode()
        return
    if EXPLAIN_PATH:
        explain_mode()
        return
    aggressive = FULL
    mode = 'AGGRESSIVE' if AGGRESSIVE else ('DEEP' if DEEP else ('FULL' if FULL else 'SAFE'))
    try:
        free0 = shutil.disk_usage('C:\\').free
    except OSError:
        free0 = None
    
    # v6: Admin check for privileged targets
    admin_status = ' (admin)' if is_admin() else ''
    print('StorageCleaner v9.1 [%s]%s - scanning caches...' % (mode, admin_status))
    if free0 is not None:
        print('C: free space now: %s' % fmt(free0))
    
    rows = measure(build_targets())

    # Session sweeps, recycle bin and playwright stay gated behind --full.
    if not aggressive:
        rows = [(lbl, p, None, 'skipped (--full)', 0)
                if (lbl.startswith(SESSION_LABELS) or lbl.startswith('recycle bin')
                    or lbl == 'playwright browsers') else (lbl, p, fn, st, sz)
                for lbl, p, fn, st, sz in rows]

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

    # v9: report-only folders are never deleted, so only measure them when the
    # user asked for a report. This was 26.7s of every scan, including -q runs.
    if REPORT:
        print('\nReport-only (needs your judgement - not deleted):')
        ro = [(lbl, p) for lbl, p in REPORT_ONLY
              if not (FULL and lbl in REPORT_ONLY_SKIP_WHEN_FULL)
              and not (AGGRESSIVE and lbl in REPORT_ONLY_SKIP_WHEN_AGGRESSIVE)
              and os.path.isdir(p)]
        with ThreadPoolExecutor(max_workers=SIZE_WORKERS) as ex:
            sizes = list(ex.map(lambda i: dir_size(i[1]), ro))
        for (lbl, p), sz in zip(ro, sizes):
            print('  %-28s %10s' % (lbl[:28], fmt(sz)))

    model = load_model()
    if model:
        acc = model.get('holdout_accuracy', model.get('train_accuracy', 0))
        extra = ''
        if 'hard_neg_fp' in model:
            extra = ', hard-neg FP %d, hard-pos recall %.2f' % (
                model['hard_neg_fp'], model.get('hard_pos_recall', 0))
        print('\nAI model: loaded (brain %s, holdout acc %.0f%%%s)' % (
            model.get('brain', '?'), acc * 100, extra))
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
    hunt_freed = hunt_count = hunt_with_data = 0
    for label, path, fn, status, size in rows:
        if fn is None:
            continue
        try:
            freed, note = fn()
        except Exception as e:
            freed, note = 0, 'error: %r' % e
        freed_total += max(freed, 0)
        if label.startswith('hunt '):
            # Hundreds of discovered caches are noise on the console - one
            # aggregate line there, every full path in the log for auditing.
            hunt_freed += max(freed, 0)
            hunt_count += 1
            if freed > 0:
                hunt_with_data += 1
            log('hunt %-52s %10s   %s' % (label, fmt(max(freed, 0)), note))
            continue
        if freed > 0 or (note != 'not present' and note != 'already empty'):
            line = '  %-26s %10s   %s' % (label[:26], fmt(max(freed, 0)), note)
            print(line)
            log(line.strip())
    if hunt_count:
        line = '  %-26s %10s   %d discovered cache folders (%d had data)' % (
            'hunt caches', fmt(hunt_freed), hunt_count, hunt_with_data)
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
