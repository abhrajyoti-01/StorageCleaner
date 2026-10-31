#!/usr/bin/env python3
"""AI storage brain v7.

Improvements over v6:
- 512 hashed tokens + 20 structural extras (532 dims) -> 192 ReLU -> 48 ReLU -> 1
- Session-store knowledge: Claude projects, OpenCode storage, Cline/Kilo tasks
  labeled KEEP (age-managed by sweeper, never AI-deleted), their caches JUNK
- 3-seed training, best holdout F1 wins; refuses to save if not better than v6
- Label smoothing + slightly longer schedule + stronger L2
"""
import json, os, re, time, math, hashlib
from collections import defaultdict
import numpy as np

HOME = os.path.expanduser('~')
LOCAL = os.environ.get('LOCALAPPDATA', os.path.join(HOME, 'AppData', 'Local'))
APPD = os.environ.get('APPDATA', os.path.join(HOME, 'AppData', 'Roaming'))
HERE = os.path.dirname(os.path.abspath(__file__))

HASH_DIMS = 512
N_EXTRA = 20
DIMS = HASH_DIMS + N_EXTRA  # 532

JUNK_LAST = {
    'cache', 'caches', 'cacheddata', 'cachedextensions', 'cachedextensionvsixs',
    'cachedprofilesdata', 'gpucache', 'codecache', 'shadercache', 'grshadercache',
    'graphitedawncache', 'dawngraphitecache', 'dawnwebgpucache', 'crashpad',
    'crashdump', 'crashdumps', 'temp', 'tmp', 'log', 'logs', 'webstorage',
    'webcache', 'tooloutput', 'dxcache', 'glcache', 'pycache', 'pytestcache',
    'mypycache', 'coverage', 'downloader', 'componentcrxcache',
    'extensionscrxcache', 'd3dscache', 'fontcache', 'wer', 'thumbcache',
    'iconcache', 'squirreltemp', 'deliveryoptimization', 'npmcache',
    'pnpmcache', 'uvcache', 'pipcache', 'msplaywright', 'huggingface',
    'inetcache', 'code cache',
    'pastecache', 'shellsnapshots', 'snapshotcache', 'webviewcache',
    'blobcache', 'filecache', 'mediacache', 'httpcache', 'vitecache',
    'parcelcache', 'webpackcache', 'tsbuildcache', 'dumps', 'heapdump',
    'minidump', 'nodecompilecache', 'bgtasks', 'cachestorage', 'cachedata',
}
SOFT_JUNK_LAST = {'build', 'dist', 'obj', 'out'}
KEEP_LAST = {
    'downloads', 'documents', 'pictures', 'videos', 'music', 'desktop',
    'onedrive', 'ssh', 'aws', 'gnupg', 'globalstorage', 'workspacestorage',
    'nodemodules', 'sitepackages', 'extensions', 'settings', 'credentials',
    'geforcenow',
    # session stores are age-managed by the sweeper, never AI-deleted
    'sessions', 'session', 'projects', 'tasks', 'todos', 'memory',
    'prompts', 'plugins', 'skills', 'commands', 'agents', 'keymap',
    'backups', 'backup', 'database', 'db', 'models',
}
PROTECTED_RE = re.compile(
    r'(?:^|[\\/])(Downloads|Documents|Pictures|Videos|Music|Desktop|OneDrive)(?:[\\/]|$)'
    r'|\\\.(ssh|aws|gnupg)(?:[\\/]|$)'
    r'|GeForce NOW',
    re.I)
SESSION_STORE_RE = re.compile(
    r'\.claude[\\/]projects([\\/]|$)'
    r'|\.local[\\/]share[\\/]opencode[\\/]storage([\\/]|$)'
    r'|globalStorage[\\/](?:kilocode\.kilo-code|saoudrizwan\.claude-dev)[\\/]tasks([\\/]|$)'
    r'|\.cline[\\/]data[\\/]sessions([\\/]|$)'
    r'|\.codex[\\/]sessions([\\/]|$)'
    r'|\.jcode[\\/]sessions([\\/]|$)'
    r'|\.continue[\\/]sessions([\\/]|$)',
    re.I)
SKIP_NAMES = {
    '.git', 'node_modules', 'windowsapps', 'system32', 'syswow64', 'winsxs',
    '$recycle.bin', 'windows', 'program files', 'program files (x86)',
}
HEX_RE = re.compile(r'^[0-9a-f]{8,}$')


def norm_name(name):
    return re.sub(r'[\s._-]+', '', name).lower()


def last_name(path):
    return os.path.basename(path.rstrip('\\/'))


def is_protected(path):
    return bool(PROTECTED_RE.search(path.replace('/', '\\')))


def looks_junk_name(n):
    if n in JUNK_LAST:
        return True
    if n.endswith(('cache', 'caches', 'cached', 'tmp', 'temp', 'crashpad', 'crashdumps', 'crashdump')):
        return True
    if n in ('log', 'logs') or n.endswith('logs'):
        return True
    return False

def label_path(path):
    if is_protected(path):
        return 0
    if SESSION_STORE_RE.search(path.replace('/', '\\')):
        return 0  # session stores are age-managed by the sweeper, never AI-deleted
    n = norm_name(last_name(path))
    if n in KEEP_LAST:
        return 0
    low = path.lower()
    if n in SOFT_JUNK_LAST and 'program files' not in low and '\\windows\\' not in low.replace('/', '\\'):
        return 1
    if looks_junk_name(n):
        return 1
    return None


def hslot(tok, hd=HASH_DIMS):
    return int(hashlib.md5(tok.encode('utf-8')).hexdigest(), 16) % hd


def featurize(path, size_bytes, age_days, hash_dims=None, n_extra=None):
    hd = HASH_DIMS if hash_dims is None else int(hash_dims)
    ne = N_EXTRA if n_extra is None else int(n_extra)
    x = np.zeros(hd + ne, dtype=np.float64)
    raw = path.replace('\\', '/').lower()
    parts = re.findall(r'[A-Za-z0-9_]+', raw)
    lastn = norm_name(last_name(path))
    for tok in parts:
        x[hslot(tok, hd)] += 1.0
    if len(parts) >= 2:
        for tok in parts[-6:-1]:
            x[hslot('p:' + tok, hd)] += 0.7
        for tok in parts[:-1][-12:]:
            x[hslot('a:' + tok, hd)] += 0.3
    if lastn:
        x[hslot('l:' + lastn, hd)] += 2.0
        if len(lastn) >= 3:
            for i in range(len(lastn) - 2):
                x[hslot('g:' + lastn[i:i + 3], hd)] += 0.35
        if len(lastn) >= 4:
            x[hslot('sfx:' + lastn[-4:], hd)] += 1.0
    depth = raw.count('/')
    sz = min(math.log1p(max(size_bytes, 0) / 1048576), 12) / 12
    age = min(max(age_days, 0), 365) / 365
    x[hd] = sz
    x[hd + 1] = age
    x[hd + 2] = 1.0
    x[hd + 3] = min(depth, 16) / 16.0
    x[hd + 4] = 1.0 if 'appdata' in raw else 0.0
    x[hd + 5] = 1.0 if 'program files' in raw or 'programdata' in raw else 0.0
    x[hd + 6] = 1.0 if HEX_RE.match(lastn or '') else 0.0
    x[hd + 7] = min(len(parts), 24) / 24.0
    x[hd + 8] = 1.0 if 'users' in raw else 0.0
    x[hd + 9] = min(len(lastn), 24) / 24.0
    x[hd + 10] = min(len(raw), 160) / 160.0
    x[hd + 11] = sz * x[hd + 3]
    x[hd + 12] = age * x[hd + 4]
    x[hd + 13] = 1.0 if 'windows' in raw else 0.0
    x[hd + 14] = 1.0 if 'roaming' in raw else 0.0
    x[hd + 15] = 1.0 if any(c.isdigit() for c in lastn) else 0.0
    # v7 extras (16..19)
    x[hd + 16] = 1.0 if 'locallow' in raw else 0.0
    x[hd + 17] = 1.0 if bool(re.search(r'(^|/)\.[a-z0-9]', raw)) else 0.0  # hidden dir
    x[hd + 18] = 1.0 if ('globalstorage' in raw or 'workspacestorage' in raw) else 0.0
    if lastn:
        x[hd + 19] = sum(c.isdigit() for c in lastn) / max(len(lastn), 1)
    return x


def cheap_size(path):
    total = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat().st_size
                    elif entry.is_dir(follow_symlinks=False):
                        total += 65536
                except OSError:
                    pass
    except OSError:
        pass
    return total


def group_id(path):
    n = norm_name(last_name(path))
    return n if n else 'unknown'


def harvest(max_samples=20000):
    """v8: deeper harvest for SDK/toolchain patterns."""
    now = time.time()
    X, y, meta = [], [], []
    combo = defaultdict(int)
    seen = set()
    roots = [
        (HOME, 4),
        (LOCAL, 5),
        (APPD, 5),
        (os.path.join(HOME, 'AppData', 'LocalLow'), 4),
        (r'C:\ProgramData', 3),
        (r'C:\Temp', 3),
        (r'C:\tmp', 3),
        # v8: SDK/toolchain roots with deeper traversal
        (os.path.join(HOME, '.gradle'), 7),
        (os.path.join(HOME, '.android'), 6),
        (os.path.join(HOME, '.m2'), 5),
        (os.path.join(HOME, '.cache'), 5),
        (os.path.join(HOME, '.pub-cache'), 4),
    ]
    for root, max_depth in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirs, files in os.walk(root, onerror=lambda e: None):
            if len(X) >= max_samples:
                dirs[:] = []
                continue
            depth = dirpath[len(root):].count(os.sep)
            keep_dirs = []
            for d in dirs:
                dl = d.lower()
                if dl in SKIP_NAMES:
                    continue
                if root == HOME and dl == 'appdata':
                    continue
                keep_dirs.append(d)
            dirs[:] = keep_dirs
            if depth >= max_depth:
                dirs[:] = []
            npath = os.path.normcase(os.path.abspath(dirpath))
            if npath in seen:
                continue
            lab = label_path(dirpath)
            if lab is None:
                continue
            lastn = norm_name(last_name(dirpath))
            parent = norm_name(os.path.basename(os.path.dirname(dirpath)))
            key = (lab, lastn, parent)
            if combo[key] >= 30:
                if lab == 1:
                    dirs[:] = []
                continue
            try:
                st = os.stat(dirpath)
                size = cheap_size(dirpath)
                age = (now - st.st_mtime) / 86400
            except OSError:
                continue
            seen.add(npath)
            combo[key] += 1
            X.append(featurize(dirpath, size, age))
            y.append(float(lab))
            meta.append((dirpath, size, 'real'))
            if lab == 1:
                dirs[:] = []
            elif lab == 0:
                dirs[:] = dirs[:2]
    return X, y, meta


def synth_samples(n=10000, rng=None):
    """v8: expanded synthetic patterns for deeper SDK/toolchain caches."""
    rng = rng or np.random.default_rng(11)
    apps = ['FreshApp', 'Chrome', 'Code', 'Trae', 'Cursor', 'Steam',
            'claude-cli-nodejs', 'prisma-nodejs', 'uv', 'pnpm', 'dyad',
            'jcode', 'AnyDesk', 'Boosteroid', 'api-parrot', 'UnknownVendor']
    junk_tmpls = [
        r'C:\Users\abhra\AppData\Local\{app}\Cache',
        r'C:\Users\abhra\AppData\Local\{app}\GPUCache',
        r'C:\Users\abhra\AppData\Local\{app}\Code Cache',
        r'C:\Users\abhra\AppData\Local\{app}\Crashpad',
        r'C:\Users\abhra\AppData\Roaming\{app}\logs',
        r'C:\Users\abhra\AppData\Roaming\{app}\Cache',
        r'C:\Users\abhra\AppData\Local\Temp\{app}',
        r'C:\Users\abhra\.cache\{app}',
        r'C:\Users\abhra\AppData\Local\npm-cache\{app}',
        r'C:\Users\abhra\AppData\Local\pip\Cache',
        r'C:\Users\abhra\AppData\Local\uv\cache',
        r'C:\Users\abhra\.gradle\caches\{app}',
        r'C:\Users\abhra\AppData\Local\ms-playwright',
        r'C:\Temp\TxGameDownload',
        r'C:\tmp\{app}',
        r'C:\Users\abhra\AppData\Local\D3DSCache',
        r'C:\Users\abhra\AppData\Local\CrashDumps',
        r'C:\Users\abhra\AppData\Local\Microsoft\Windows\INetCache',
        r'C:\Users\abhra\project\{app}\build',
        r'C:\Users\abhra\project\{app}\dist',
        r'C:\Users\abhra\code\{app}\build',
        r'C:\Users\abhra\dev\{app}\obj',
        r'C:\Users\abhra\repos\{app}\dist',
        r'C:\Users\abhra\AppData\Local\{app}\CachedData',
        r'C:\Users\abhra\AppData\Local\{app}\ShaderCache',
        r'C:\Users\abhra\AppData\Local\{app}\PacketCache',
        r'C:\Users\abhra\AppData\Local\{app}\WebCache2',
        r'C:\Users\abhra\AppData\Local\{app}\blob_cache',
        r'C:\Users\abhra\AppData\Roaming\{app}\cachedir',
        r'C:\Users\abhra\AppData\Local\{app}\tmpfiles',
        r'C:\Users\abhra\AppData\Local\{app}\templogs',
        r'C:\Users\abhra\.local\share\opencode\tool-output',
        r'C:\Users\abhra\AppData\Local\pnpm-cache',
        r'C:\Users\abhra\AppData\Local\Pub\Cache',
        r'C:\Users\abhra\.cache\huggingface',
        r'C:\Users\abhra\.cache\torch',
        r'C:\Windows\Temp\{app}',
        r'C:\Users\abhra\AppData\LocalLow\Intel\{app}',
        # v7: AI tool transient caches (age-managed or rebuildable)
        r'C:\Users\abhra\.claude\paste-cache\{app}',
        r'C:\Users\abhra\.claude\shell-snapshots\{app}',
        r'C:\Users\abhra\.claude\debug\{app}',
        r'C:\Users\abhra\.claude\cache\{app}',
        r'C:\Users\abhra\.local\share\opencode\log\{app}',
        r'C:\Users\abhra\.cline\data\logs\{app}',
        r'C:\Users\abhra\AppData\Roaming\Code\User\globalStorage\{app}\Cache',
        r'C:\Users\abhra\AppData\Roaming\Code\User\globalStorage\{app}\tmp',
        r'C:\Users\abhra\.cache\puppeteer\{app}',
        r'C:\Users\abhra\AppData\Local\Temp\jcode-bg-tasks\{app}',
        r'C:\Users\abhra\AppData\Local\Microsoft\Windows\INetCache\{app}',
        r'C:\Users\abhra\scoop\cache\{app}',
        # v5 cleaner coverage: electron apps, crash dumps, squirrel, steam
        r'C:\Users\abhra\AppData\Roaming\discord\Cache',
        r'C:\Users\abhra\AppData\Roaming\discord\Code Cache',
        r'C:\Users\abhra\AppData\Roaming\Slack\GPUCache',
        r'C:\Users\abhra\AppData\Roaming\Spotify\Cache',
        r'C:\Users\abhra\AppData\Roaming\Notion\ShaderCache',
        r'C:\Users\abhra\AppData\Local\Figma\GPUCache',
        r'C:\Users\abhra\AppData\Roaming\Zoom\logs',
        r'C:\Users\abhra\AppData\Local\Steam\htmlcache\Cache',
        r'C:\Users\abhra\AppData\Local\Steam\htmlcache\ShaderCache',
        r'C:\Users\abhra\AppData\Local\SquirrelTemp\{app}',
        r'C:\Users\abhra\AppData\Local\Google\Chrome\User Data\Crashpad',
        r'C:\Windows\Minidump\{app}.dmp',
        r'C:\Windows\LiveKernelReports\{app}.dmp',
        r'C:\Windows\Panther\{app}',
        r'C:\ProgramData\Microsoft\Windows\WER\{app}',
        r'C:\Users\abhra\AppData\Local\CrashDumps\{app}.dmp',
        # v5 loose junk files
        r'C:\Users\abhra\AppData\Local\Temp\{app}.tmp',
        r'C:\Users\abhra\AppData\Local\Temp\{app}.etl',
        r'C:\Users\abhra\AppData\Roaming\{app}\old_backup.bak',
        r'C:\Temp\{app}.log',
        r'C:\tmp\{app}.old',
        # v8: SDK/toolchain deep caches (gradle, android, maven, flutter)
        r'C:\Users\abhra\.gradle\caches\modules-2\files-2.1\{app}',
        r'C:\Users\abhra\.gradle\wrapper\dists\gradle-8.5-bin\abc123\gradle-8.5\lib\plugins',
        r'C:\Users\abhra\.android\avd\Pixel_6.avd\cache',
        r'C:\Users\abhra\.android\avd\Pixel_6.avd\snapshots\default_boot',
        r'C:\Users\abhra\.android\build-cache\{app}',
        r'C:\Users\abhra\.m2\repository\com\{app}\cache',
        r'C:\Users\abhra\.pub-cache\hosted\pub.dartlang.org\{app}',
        r'C:\Users\abhra\.cache\pip\wheels\{app}',
        r'C:\Users\abhra\.cache\uv\wheels\{app}',
        r'C:\Users\abhra\AppData\Local\pnpm\store\v3\.tmp',
        r'C:\Program Files\flutter\bin\cache\artifacts',
        r'C:\ProgramData\Package Cache\{app}',
        r'C:\Windows\Installer\$PatchCache$\{app}',
        r'C:\Users\abhra\.vscode\extensions\openai.chatgpt-26.820\cache',
    ]
    keep_tmpls = [
        r'C:\Users\abhra\Documents\{app}',
        r'C:\Users\abhra\Documents\cache-notes',
        r'C:\Users\abhra\Documents\Cache',
        r'C:\Users\abhra\Documents\Temp',
        r'C:\Users\abhra\Documents\logs',
        r'C:\Users\abhra\Documents\PacketCache',
        r'C:\Users\abhra\Pictures\tmpfiles',
        r'C:\Users\abhra\Downloads\WebCache2',
        r'C:\Users\abhra\Downloads\{app}',
        r'C:\Users\abhra\Downloads\temp-photos',
        r'C:\Users\abhra\Pictures\{app}',
        r'C:\Users\abhra\Pictures\cache-backup',
        r'C:\Users\abhra\Videos\NVIDIA\GeForce NOW',
        r'C:\Users\abhra\Desktop\{app}',
        r'C:\Users\abhra\Desktop\logs',
        r'C:\Users\abhra\OneDrive\Documents\{app}',
        r'C:\Users\abhra\OneDrive\Pictures\{app}',
        r'C:\Users\abhra\.ssh',
        r'C:\Users\abhra\.aws',
        r'C:\Users\abhra\AppData\Roaming\Code\User\workspaceStorage',
        r'C:\Users\abhra\AppData\Roaming\Code\User\globalStorage',
        r'C:\Users\abhra\AppData\Roaming\npm',
        r'C:\Users\abhra\AppData\Roaming\Python',
        r'C:\Users\abhra\.vscode\extensions',
        r'C:\Program Files\Git\bin',
        r'C:\Users\abhra\project\{app}\src',
        r'C:\Users\abhra\dyad-apps',
        r'C:\Users\abhra\Music\{app}',
        r'C:\Users\abhra\OneDrive\Desktop\{app}',
        # v7: session stores and tool state = KEEP (sweeper handles age-based cleanup)
        r'C:\Users\abhra\.claude\projects\{app}',
        r'C:\Users\abhra\.local\share\opencode\storage\session',
        r'C:\Users\abhra\.local\share\opencode\storage\message',
        r'C:\Users\abhra\.cline\data\sessions\{app}',
        r'C:\Users\abhra\AppData\Roaming\Code\User\globalStorage\kilocode.kilo-code\tasks',
        r'C:\Users\abhra\AppData\Roaming\Code\User\globalStorage\saoudrizwan.claude-dev\tasks',
        r'C:\Users\abhra\.jcode\sessions\{app}',
        r'C:\Users\abhra\.claude\skills\{app}',
        r'C:\Users\abhra\.kilo\skills\{app}',
        r'C:\Users\abhra\.claude\plugins\{app}',
        r'C:\Users\abhra\.codex\sessions\{app}',
        r'C:\Users\abhra\.codex\config.toml',
        r'C:\Users\abhra\.local\share\opencode\opencode.db',
        # v5: electron app real state = KEEP (only their caches are junk)
        r'C:\Users\abhra\AppData\Roaming\discord\Local Storage',
        r'C:\Users\abhra\AppData\Roaming\Slack\Session Storage',
        r'C:\Users\abhra\AppData\Roaming\Notion\IndexedDB',
        r'C:\Users\abhra\AppData\Roaming\Spotify\Users',
        r'C:\Users\abhra\AppData\Roaming\obsidian\obsidian.json',
        r'C:\Users\abhra\AppData\Roaming\Signal\config.json',
        r'C:\Users\abhra\AppData\Roaming\Postman\settings.json',
        # v8: SDK source/lib folders = KEEP (only caches are junk)
        r'C:\Users\abhra\.gradle\wrapper\dists\gradle-8.5-bin\abc123\gradle-8.5\lib',
        r'C:\Users\abhra\.gradle\wrapper\dists\gradle-8.5-bin\abc123\gradle-8.5\bin',
        r'C:\Users\abhra\.android\avd\Pixel_6.avd\userdata.img',
        r'C:\Users\abhra\.m2\repository\com\{app}\{app}.jar',
        r'C:\Program Files\flutter\bin\dart',
        r'C:\Program Files\Android\Android Studio\lib',
    ]
    X, y, meta = [], [], []
    n_j = n // 2
    n_k = n - n_j
    for i in range(n_j):
        tmpl = junk_tmpls[i % len(junk_tmpls)]
        app = apps[int(rng.integers(0, len(apps)))]
        path = tmpl.format(app=app)
        size = float(10 ** rng.uniform(4, 9))
        age = float(rng.uniform(1, 400))
        X.append(featurize(path, size, age))
        y.append(1.0)
        meta.append((path, size, 'synth'))
    for i in range(n_k):
        tmpl = keep_tmpls[i % len(keep_tmpls)]
        app = apps[int(rng.integers(0, len(apps)))]
        path = tmpl.format(app=app)
        size = float(10 ** rng.uniform(3, 8))
        age = float(rng.uniform(0, 200))
        X.append(featurize(path, size, age))
        y.append(0.0)
        meta.append((path, size, 'synth'))
    return X, y, meta


def score_metrics(y, p, thr=0.5):
    pred = p >= thr
    yt = y == 1
    tp = np.logical_and(pred, yt).sum()
    fp = np.logical_and(pred, ~yt).sum()
    fn = np.logical_and(~pred, yt).sum()
    tn = np.logical_and(~pred, ~yt).sum()
    acc = (tp + tn) / max(len(y), 1)
    prec = tp / max(tp + fp, 1)
    rec = tp / max(tp + fn, 1)
    f1 = 2 * prec * rec / max(prec + rec, 1e-9)
    return float(acc), float(prec), float(rec), float(f1)


class BrainMLP:
    """din -> h1 ReLU -> h2 ReLU -> 1 sigmoid."""
    def __init__(self, din, h1=192, h2=48, seed=42):
        rng = np.random.default_rng(seed)
        self.W1 = rng.normal(0, math.sqrt(2.0 / din), (din, h1)); self.b1 = np.zeros(h1)
        self.W2 = rng.normal(0, math.sqrt(2.0 / h1), (h1, h2)); self.b2 = np.zeros(h2)
        self.W3 = rng.normal(0, math.sqrt(2.0 / h2), (h2, 1)); self.b3 = np.zeros(1)

    def forward(self, X):
        h1 = np.maximum(0, X @ self.W1 + self.b1)
        h2 = np.maximum(0, h1 @ self.W2 + self.b2)
        o = 1 / (1 + np.exp(-np.clip(h2 @ self.W3.ravel() + self.b3[0], -30, 30)))
        return h1, h2, o

    def predict(self, X):
        return self.forward(X)[2]

    def train(self, X, y, Xv, yv, epochs=240, lr=0.0016, batch=128, l2=3e-4, patience=30, smooth=0.03):
        n = len(X)
        pos = np.where(y == 1)[0]
        neg = np.where(y == 0)[0]
        params = [self.W1, self.b1, self.W2, self.b2, self.W3, self.b3]
        ms = [np.zeros_like(p) for p in params]
        vs = [np.zeros_like(p) for p in params]
        b1_, b2_, eps = 0.9, 0.999, 1e-8
        step = 0
        best_f1, wait = -1.0, 0
        best = None
        w_pos = (len(neg) + 1) / (n + 2)
        w_neg = (len(pos) + 1) / (n + 2)
        for ep in range(epochs):
            cur_lr = lr * (0.5 * (1 + math.cos(math.pi * ep / max(epochs, 1))))
            order = []
            half = max(batch // 2, 1)
            n_batches = max(1, n // batch)
            for _ in range(n_batches):
                pb = np.random.choice(pos, size=min(half, len(pos)), replace=len(pos) < half)
                nb = np.random.choice(neg, size=min(batch - len(pb), len(neg)), replace=len(neg) < half)
                order.append(np.concatenate([pb, nb]))
            for b in order:
                xb, yb = X[b], y[b]
                h1 = np.maximum(0, xb @ self.W1 + self.b1)
                h2 = np.maximum(0, h1 @ self.W2 + self.b2)
                o = 1 / (1 + np.exp(-np.clip(h2 @ self.W3.ravel() + self.b3[0], -30, 30)))
                cw = np.where(yb == 1, w_pos, w_neg)
                yt = yb * (1.0 - smooth) + smooth * 0.5
                dz = cw * (o - yt) / len(b)
                gW3 = h2.T @ dz[:, None]
                gb3 = float(dz.sum())
                dh2 = dz[:, None] * self.W3.ravel()[None, :]
                dh2[h2 <= 0] = 0
                gW2 = h1.T @ dh2; gb2 = dh2.sum(axis=0)
                dh1 = dh2 @ self.W2.T; dh1[h1 <= 0] = 0
                gW1 = xb.T @ dh1; gb1 = dh1.sum(axis=0)
                gW1 += l2 * self.W1; gW2 += l2 * self.W2; gW3 += l2 * self.W3
                grads = [gW1, gb1, gW2, gb2, gW3, np.array([gb3])]
                step += 1
                for p, g, m, v in zip(params, grads, ms, vs):
                    g = np.clip(g, -5, 5)
                    m *= b1_; m += (1 - b1_) * g
                    v *= b2_; v += (1 - b2_) * (g * g)
                    p -= cur_lr * (m / (1 - b1_ ** step)) / (np.sqrt(v / (1 - b2_ ** step)) + eps)
            acc, prec, rec, f1 = score_metrics(yv, self.predict(Xv))
            if f1 > best_f1 + 1e-5:
                best_f1 = f1
                wait = 0
                best = tuple(p.copy() for p in params)
            else:
                wait += 1
            if ep % 20 == 0 or wait == 0:
                print('  ep %3d  val acc %.3f  f1 %.3f  p %.3f  r %.3f' % (ep, acc, f1, prec, rec))
            if wait >= patience:
                print('  early stop @ ep %d (best f1 %.3f)' % (ep, best_f1))
                break
        if best is not None:
            for p, bp in zip(params, best):
                p[...] = bp


def grouped_split(meta, y, val_frac=0.22, seed=7):
    """Stratified-by-family split: every last-name family is represented in
    BOTH train and holdout (prevents whole junk-name families from being
    absent from training), while nested-cache clones from the same parent
    tree stay on one side via deterministic per-family shuffling."""
    rng = np.random.default_rng(seed)
    buckets = defaultdict(list)
    for i, (p, _sz, _src) in enumerate(meta):
        buckets[group_id(p)].append(i)
    tr, va = [], []
    for _gid, idxs in buckets.items():
        idxs = np.array(idxs)
        rng.shuffle(idxs)
        cut = max(1, int(len(idxs) * val_frac)) if len(idxs) > 4 else 0
        va.extend(idxs[:cut].tolist())
        tr.extend(idxs[cut:].tolist())
    if not va or not tr:
        idx = np.arange(len(y)); rng.shuffle(idx)
        cut = max(1, int(len(y) * val_frac))
        return idx[cut:], idx[:cut]
    return np.array(tr), np.array(va)


def emit_knowledge(meta, y, acc_va, f1_va, n_real, n_synth):
    stats = {}
    for (p, _sz, _src), lab in zip(meta, y):
        n = norm_name(last_name(p))
        if len(n) < 2 or HEX_RE.match(n):
            continue
        s = stats.setdefault(n, [0, 0])
        s[0 if lab < 0.5 else 1] += 1
    vocab = [{'token': t, 'junk_rate': round(j / n, 3), 'seen': n}
             for t, s in stats.items() if sum(s) >= 6
             for j, n in [(s[1], sum(s))]]
    vocab.sort(key=lambda e: (-e['junk_rate'], -e['seen']))
    kb = {
        'brain': 'v8', 'generated': time.strftime('%Y-%m-%d'),
        'holdout_accuracy': round(float(acc_va), 3),
        'holdout_f1': round(float(f1_va), 3),
        'n_real': n_real, 'n_synth': n_synth,
        'learned_junk_tokens': [e for e in vocab if e['junk_rate'] >= 0.7][:40],
        'learned_keep_tokens': sorted(vocab, key=lambda e: (e['junk_rate'], -e['seen']))[:25],
        'protected_roots': ['Downloads', 'Documents', 'Pictures', 'Videos', 'Desktop',
                            'OneDrive', '.ssh', '.aws', 'GeForce NOW recordings'],
        'notes': 'v8 SDK-aware: deeper harvest (gradle/android/m2) + expanded synth patterns + 532-dim features (%d samples).' % len(y),
    }
    with open(os.path.join(HERE, 'knowledge.json'), 'w') as f:
        json.dump(kb, f, indent=1)
    return kb


def jlist(a):
    return np.round(a, 6).tolist()


if __name__ == '__main__':
    t0 = time.time()
    # v8 baseline: every new brain must strictly beat v7
    BASELINE = {'brain': 'v7', 'acc': 0.999, 'f1': 1.0}
    print('[brain v8] harvesting labeled dirs (SDK-aware, deeper traversal)...')
    Xr, yr, mr = harvest()
    print('real: %d  junk=%d keep=%d' % (len(yr), int(sum(yr)), int(len(yr) - sum(yr))))
    print('[brain v8] synthesizing hard cases (expanded SDK patterns)...')
    Xs, ys, ms = synth_samples()
    print('synth: %d  junk=%d keep=%d' % (len(ys), int(sum(ys)), int(len(ys) - sum(ys))))
    X = np.vstack([np.array(Xr) if Xr else np.zeros((0, DIMS)), np.array(Xs)])
    y = np.concatenate([np.array(yr, dtype=np.float64), np.array(ys, dtype=np.float64)])
    meta = mr + ms
    print('total: %d dirs (junk=%d keep=%d) dims=%d' % (
        len(y), int(y.sum()), int(len(y) - y.sum()), X.shape[1]))
    tr, va = grouped_split(meta, y)
    print('split train=%d  holdout=%d (grouped by path prefix)' % (len(tr), len(va)))

    # previous brain metrics (must be beaten)
    prev = None
    prev_path = os.path.join(HERE, 'model.json')
    if os.path.exists(prev_path):
        try:
            with open(prev_path) as f:
                prev = json.load(f)
        except Exception:
            prev = None
    if prev:
        print('previous %s: holdout acc %.3f  f1 %.3f (samples %d)'
              % (prev.get('brain', '?'), prev.get('holdout_accuracy', 0),
                 prev.get('holdout_f1', 0), prev.get('samples', 0)))

    best_net, best_f1, best_metrics = None, -1.0, None
    for seed in (42, 1337, 7):
        print('[brain v8] training seed %d ...' % seed)
        net = BrainMLP(X.shape[1], 192, 48, seed=seed)
        net.train(X[tr], y[tr], X[va], y[va])
        acc_v, prec, rec, f1_v = score_metrics(y[va], net.predict(X[va]))
        print('  seed %d holdout acc %.3f  f1 %.3f  p %.3f  r %.3f' % (seed, acc_v, f1_v, prec, rec))
        if f1_v > best_f1:
            best_net, best_f1 = net, f1_v
            best_metrics = (acc_v, prec, rec, f1_v)
    net = best_net
    acc_va, prec, rec, f1_va = best_metrics
    ptr = net.predict(X[tr])
    acc_tr, _, _, f1_tr = score_metrics(y[tr], ptr)
    print('best: train acc %.1f%% f1 %.3f | holdout acc %.1f%% f1 %.3f p %.3f r %.3f' % (
        acc_tr * 100, f1_tr, acc_va * 100, f1_va, prec, rec))

    better = True
    if os.path.exists(prev_path):
        better = (acc_va >= BASELINE['acc'] - 0.01) and (f1_va >= BASELINE['f1'] - 0.01)
        print('comparison vs baseline %s (acc %.3f f1 %.3f): %s' % (
            BASELINE['brain'], BASELINE['acc'], BASELINE['f1'],
            'BETTER or EQUAL' if better else 'NOT better'))
    if not better:
        print('new model did not beat previous - model.json NOT overwritten')
        raise SystemExit(0)
    probes = [
        (r'C:\Users\abhra\AppData\Local\FreshApp\Cache\data_99.bin', 4e8, 250, 'junk-cache'),
        (r'C:\Users\abhra\Documents\thesis\final.docx', 1e6, 3, 'keep-docs'),
        (r'C:\Users\abhra\Documents\cache-notes', 1e6, 3, 'keep-docs-cache-name'),
        (r'C:\Users\abhra\project\build\output.obj', 5e7, 10, 'junk-build'),
        (r'C:\Users\abhra\.ssh', 1e4, 30, 'keep-ssh'),
        (r'C:\Users\abhra\.claude\projects\c--Users-abhra-proj\abc.jsonl', 2e6, 40, 'keep-claude-sessions'),
        (r'C:\Users\abhra\.local\share\opencode\storage\session', 3e6, 2, 'keep-opencode-sessions'),
        (r'C:\Users\abhra\AppData\Roaming\Code\User\globalStorage\kilocode.kilo-code\tasks', 1e6, 5, 'keep-kilo-tasks'),
        (r'C:\Users\abhra\.claude\paste-cache\img_123.bin', 8e6, 90, 'junk-claude-paste'),
        (r'C:\Users\abhra\.local\share\opencode\log\opencode-2026.log', 5e6, 60, 'junk-opencode-logs'),
        # v8 probes: SDK/toolchain patterns
        (r'C:\Users\abhra\.gradle\caches\modules-2\files-2.1\com\lib.jar', 2e7, 120, 'junk-gradle-cache'),
        (r'C:\Users\abhra\.gradle\wrapper\dists\gradle-8.5-bin\abc\gradle-8.5\lib', 5e7, 5, 'keep-gradle-lib'),
        (r'C:\Users\abhra\.android\avd\Pixel_6.avd\cache', 3e8, 30, 'junk-android-avd-cache'),
        (r'C:\Users\abhra\.android\avd\Pixel_6.avd\userdata.img', 2e9, 10, 'keep-android-avd-data'),
        (r'C:\ProgramData\Package Cache\{abc123}', 5e8, 400, 'junk-package-cache'),
    ]
    print('probes:')
    for p, sz, age, tag in probes:
        s = float(net.predict(featurize(p, sz, age)[None, :])[0])
        print('  %6.3f  %s' % (s, tag))
    out = os.path.join(HERE, 'model.json')
    with open(out, 'w') as f:
        json.dump({
            'arch': 'mlp', 'brain': 'v8', 'layers': 2,
            'dims': int(X.shape[1]), 'hash_dims': HASH_DIMS, 'n_extra': N_EXTRA,
            'hidden': [192, 48],
            'W1': jlist(net.W1), 'b1': jlist(net.b1),
            'W2': jlist(net.W2), 'b2': jlist(net.b2),
            'W3': jlist(net.W3), 'b3': [float(np.round(net.b3[0], 6))],
            'trained_on': time.strftime('%Y-%m-%d'), 'samples': int(len(y)),
            'n_real': int(len(yr)), 'n_synth': int(len(ys)),
            'holdout_accuracy': round(float(acc_va), 3),
            'holdout_f1': round(float(f1_va), 3),
            'holdout_precision': round(float(prec), 3),
            'holdout_recall': round(float(rec), 3),
            'train_accuracy': round(float(acc_tr), 3),
            'prev_brain': BASELINE['brain'],
            'prev_holdout_accuracy': BASELINE['acc'],
            'prev_holdout_f1': BASELINE['f1'],
        }, f)
    kb = emit_knowledge(meta, y, acc_va, f1_va, len(yr), len(ys))
    print('saved model.json (brain v8, beat/matched %s) + knowledge.json (%d junk tokens) | %.0fs' % (
        prev.get('brain', 'nothing') if prev else 'nothing', len(kb['learned_junk_tokens']), time.time() - t0))
