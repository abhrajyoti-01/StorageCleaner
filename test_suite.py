#!/usr/bin/env python3
"""Test suite for StorageCleaner brain + core logic. Run: python test_suite.py"""
import json, os, sys, time, re, tempfile, shutil
import importlib.util as iu

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
PASS = FAIL = 0
def check(name, cond):
    global PASS, FAIL
    print(('  PASS  ' if cond else '  FAIL  ') + name)
    PASS, FAIL = PASS + (1 if cond else 0), FAIL + (0 if cond else 1)

def load_module(name, filename):
    spec = iu.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = iu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

print('=== model artifact ===')
with open(os.path.join(HERE, 'model.json')) as f:
    M = json.load(f)
check('model arch is mlp + brain v9', M.get('arch') == 'mlp' and M.get('brain') == 'v9')
check('two hidden layers [192, 48]', M.get('hidden') == [192, 48])
check('holdout accuracy >= 0.90', M.get('holdout_accuracy', 0) >= 0.90)
check('trained on mixed real+synth >= 3000', M.get('samples', 0) >= 3000)
check('hash dims 512 + 20 extras', M.get('hash_dims') == 512 and M.get('dims') == 532)
check('v9: zero hard-negative false positives', M.get('hard_neg_fp') == 0)
check('v9: hard-positive recall >= 0.90', M.get('hard_pos_recall', 0) >= 0.90)
check('v9: model is not degenerate', M.get('degenerate') is False)
check('v9: holdout F1 is not a perfect 1.0', M.get('holdout_f1', 1.0) < 0.9995)

print('=== trainer module ===')
tm = load_module('train_model_mod', 'train_model.py')
v1 = tm.featurize(r'C:\x\cache', 1000, 5)
v2 = tm.featurize(r'C:\x\cache', 1000, 5)
check('featurize deterministic', v1.tolist() == v2.tolist())
check('feature dims match model (%d)' % len(v1), len(v1) == M['dims'])
check('label AppData Cache = junk', tm.label_path(r'C:\Users\abhra\AppData\Local\FreshApp\Cache') == 1)
check('label Documents Cache = keep', tm.label_path(r'C:\Users\abhra\Documents\Cache') == 0)
check('label thesis = keep', tm.label_path(r'C:\Users\abhra\Documents\thesis') == 0)
check('label project build = junk', tm.label_path(r'C:\Users\abhra\project\build') == 1)
check('label claude projects = keep', tm.label_path(r'C:\Users\abhra\.claude\projects\proj') == 0)
check('label opencode storage = keep', tm.label_path(r'C:\Users\abhra\.local\share\opencode\storage\session') == 0)
check('label kilo tasks = keep', tm.label_path(r'C:\Users\abhra\AppData\Roaming\Code\User\globalStorage\kilocode.kilo-code\tasks') == 0)
check('label claude paste-cache = junk', tm.label_path(r'C:\Users\abhra\.claude\paste-cache') == 1)
check('label opencode log = junk', tm.label_path(r'C:\Users\abhra\.local\share\opencode\log') == 1)

print('=== tool module + AI inference ===')
sc = load_module('storagecleaner_mod', 'StorageCleaner.py')
fx = sc.featurize_for_model(r'C:\Users\abhra\AppData\Local\FreshApp\Cache', 4e8, 250, M)
tx = tm.featurize(r'C:\Users\abhra\AppData\Local\FreshApp\Cache', 4e8, 250)
check('cleaner featurize matches trainer', fx.tolist() == tx.tolist())
sc_junk = sc.ai_score(r'C:\Users\abhra\AppData\Local\FreshApp\Cache', 4e8, 250, M)
sc_keep = sc.ai_score(r'C:\Users\abhra\Documents\thesis', 1e6, 3, M)
check('tool scores junk high (%.2f)' % sc_junk, sc_junk >= 0.85)
check('tool scores keep low (%.2f)' % sc_keep, sc_keep <= 0.25)
sc_mid = sc.ai_score(r'C:\Users\abhra\project\build', 5e7, 10, M)
check('build output confidently flagged (%.2f)' % sc_mid, sc_mid >= 0.7)
sc_hard = sc.ai_score(r'C:\Users\abhra\Documents\Cache', 4e8, 250, M)
check('Documents\\Cache stays keep (%.2f)' % sc_hard, sc_hard <= 0.35)

print('=== knowledge base ===')
with open(os.path.join(HERE, 'knowledge.json')) as f:
    KB = json.load(f)
check('kb brain v9', KB.get('brain') == 'v9')
check('learned tokens > 10', len(KB['learned_junk_tokens']) > 10)
top = KB['learned_junk_tokens'][0]
check('top token junk_rate >= 0.8 (%s %.2f)' % (top['token'], top['junk_rate']),
      top['junk_rate'] >= 0.8)
check('kb records honest hard-set metrics',
      'hard_neg_fp' in KB and 'hard_pos_recall' in KB)

print('=== version parsing ===')
V_RE = re.compile(r'^(?P<id>.+?)-(?P<ver>\d+(?:\.\d+)+(?:[-+][\w.\-]+)?)$')
m = V_RE.match('openai.chatgpt-26.818.61809-win32-x64')
check('parses scoped id+version', bool(m) and m.group('id') == 'openai.chatgpt')
check('rejects no-version name', not V_RE.match('.obsolete'))
def vt(v):
    out = []
    for p in re.split(r'[.\-+]', v)[:4]:
        try: out.append(int(p))
        except ValueError: break
    while len(out) < 4: out.append(0)
    return tuple(out)
check('version compare picks newer', vt('2.10.0') > vt('2.9.9'))

print('=== clear_dir age filtering ===')
tmp = tempfile.mkdtemp()
old_f = os.path.join(tmp, 'old.txt')
new_d = os.path.join(tmp, 'newdir')
os.makedirs(new_d)
open(old_f, 'w').write('x')
open(os.path.join(new_d, 'fresh.txt'), 'w').write('x')
old_t = time.time() - 40*86400
os.utime(old_f, (old_t, old_t))
freed_old = sc.clear_dir(tmp, older_than_days=30)
check('old file removed, fresh dir preserved',
      not os.path.exists(old_f) and os.path.exists(os.path.join(new_d, 'fresh.txt')))
shutil.rmtree(tmp, ignore_errors=True)

print('=== aged_tree / aged session sweeps ===')
tmp = tempfile.mkdtemp()
sess_old = os.path.join(tmp, 'proj-a')
sess_new = os.path.join(tmp, 'proj-b')
os.makedirs(sess_old); os.makedirs(sess_new)
open(os.path.join(sess_old, 'session.jsonl'), 'w').write('x')
open(os.path.join(sess_new, 'session.jsonl'), 'w').write('x')
old_t = time.time() - 60*86400
os.utime(os.path.join(sess_old, 'session.jsonl'), (old_t, old_t))
os.utime(sess_old, (old_t, old_t))
# aged_tree: file-level aging, fresh project untouched
freed = sc.aged_tree(tmp, 30)
check('aged_tree removes only old files, keeps fresh',
      not os.path.exists(os.path.join(sess_old, 'session.jsonl')) and
      os.path.exists(os.path.join(sess_new, 'session.jsonl')))
shutil.rmtree(tmp, ignore_errors=True)
tmp = tempfile.mkdtemp()
t_old = os.path.join(tmp, 'task-old')
t_new = os.path.join(tmp, 'task-new')
os.makedirs(t_old); os.makedirs(t_new)
open(os.path.join(t_old, 'state.json'), 'w').write('x')
open(os.path.join(t_new, 'state.json'), 'w').write('x')
old_t = time.time() - 60*86400
os.utime(t_old, (old_t, old_t))
for f in os.listdir(t_old):
    os.utime(os.path.join(t_old, f), (old_t, old_t))
items = sc.aged('tasks >30d', tmp, 30, dir_mode=True)
fn = items[2]
freed, note = fn()
check('aged dir_mode removes old task dir, keeps fresh',
      not os.path.exists(t_old) and os.path.exists(t_new))
shutil.rmtree(tmp, ignore_errors=True)

print('=== v4 target coverage ===')
targets = sc.build_targets()
labels = [t[0] for t in targets]
need = ['claude sessions >30d', 'opencode sessions >30d', 'cline sessions >30d',
        'cline ext tasks >30d', 'kilo ext tasks >30d', 'continue sessions >30d',
        'jcode sessions >30d', 'claude paste cache', 'inet cache', 'scoop cache']
for n in need:
    check('target present: %s' % n, n in labels)
session_labels_needed = ['claude sessions >30d', 'opencode sessions >30d', 'cline sessions >30d',
                         'cline ext tasks >30d', 'kilo ext tasks >30d', 'continue sessions >30d',
                         'jcode sessions >30d']
check('session targets gated behind --full',
      all(lbl.startswith(sc.SESSION_LABELS) for lbl in session_labels_needed))

print('=== recycle bin SID regex ===')
txt = 'USERINFO\nabhra\\abhra S-1-5-21-86664685-934516630-1508476232-1001\n'
mm = re.search(r'S-1-5(?:-\d+)+', txt)
check('SID extracted from whoami-style output',
      bool(mm) and mm.group(0).startswith('S-1-5-21'))

print('=== deep cache hunter rules ===')
check('Cache folder is junk', bool(sc.CACHE_NAME_RE.search('Cache')))
check('GPUCache folder is junk', bool(sc.CACHE_NAME_RE.search('GPUCache')))
check('Temp folder is junk', bool(sc.CACHE_NAME_RE.search('Temp')))
check('Documents is not junk-named', not sc.CACHE_NAME_RE.search('Documents'))
check('protected skip Documents', bool(sc.HUNTER_SKIP.search(r'C:\\Users\\abhra\\Documents\\foo')))
check('chrome ShaderCache is not a real profile', not sc.BROWSER_REAL_PROFILES.match('ShaderCache'))
check('Default is a real profile', bool(sc.BROWSER_REAL_PROFILES.match('Default')))
check('Profile 18 is a real profile', bool(sc.BROWSER_REAL_PROFILES.match('Profile 18')))

print('=== loose junk file sweep ===')
check('.tmp is junk file', bool(sc.FILE_JUNK_RE.match('foo.tmp')))
check('.dmp is junk file', bool(sc.FILE_JUNK_RE.match('crash.dmp')))
check('.bak is junk file', bool(sc.FILE_JUNK_RE.match('settings.json.bak')))
check('.log is junk file', bool(sc.FILE_JUNK_RE.match('app.log')))
check('office lock ~$ is junk', bool(sc.FILE_JUNK_RE.match('~$report.docx')))
check('.crdownload is junk', bool(sc.FILE_JUNK_RE.match('video.mp4.crdownload')))
check('docx not junk file', not sc.FILE_JUNK_RE.match('report.docx'))
check('py not junk file', not sc.FILE_JUNK_RE.match('main.py'))
check('exe not junk file', not sc.FILE_JUNK_RE.match('setup.exe'))

tmp = tempfile.mkdtemp()
jf = os.path.join(tmp, 'stale.tmp')
open(jf, 'w').write('x' * 100)
lbl, _p, fn = sc.file_batch('test files', [jf])
check('file_batch preview_size precomputed', fn.preview_size == 100)
freed, note = fn()
check('file_batch removes junk files', freed == 100 and not os.path.exists(jf))
empty_d = os.path.join(tmp, 'emptydir')
os.makedirs(empty_d)
check('prune_empty_dirs removes empty', sc.prune_empty_dirs(tmp) >= 1 and not os.path.exists(empty_d))
shutil.rmtree(tmp, ignore_errors=True)

print('=== v5 target coverage ===')
targets = sc.build_targets()
labels = [t[0] for t in targets]
need_v5 = ['bsod minidumps', 'system error reports', 'setup panther logs',
           'squirrel installer temp', 'discord cache', 'steam htmlcache cache',
           'spotify cache', 'notion cache']
for n in need_v5:
    check('target present: %s' % n, n in labels)

print('=== v9 safety veto ===')
# The v8 failure: these scored >= 0.85 and would have been deleted.
VETO_MUST = [
    r'C:\Users\abhra\AppData\Roaming\Microsoft\Windows\Recent',
    r'C:\Users\abhra\AppData\Local\Microsoft\Windows\Themes',
    r'C:\Users\abhra\AppData\Local\ConnectedDevicesPlatform',
    r'C:\Users\abhra\AppData\Local\Microsoft\Windows\Explorer',
    r'C:\Users\abhra\AppData\Local\Programs',
    r'C:\Users\abhra\AppData\Local\Packages\App\LocalState',
    r'C:\Users\abhra\Documents\Cache',
    r'C:\Users\abhra\Downloads\WebCache2',
    r'C:\Users\abhra\Pictures\cache-backup',
    r'C:\Users\abhra\OneDrive\Documents\x',
    r'C:\Users\abhra\.ssh',
    r'C:\Users\abhra\.aws',
    r'C:\Users\abhra\AppData\Roaming\Code\User\globalStorage',
    r'C:\Users\abhra\AppData\Roaming\Code\User\workspaceStorage',
    r'C:\Users\abhra\.codex\sessions',
]
for p in VETO_MUST:
    check('veto blocks %s' % p.split('\\')[-1], sc.safety_veto(p)[0])

# Legitimate caches must survive the veto.
VETO_MUST_NOT = [
    r'C:\Users\abhra\AppData\Local\npm-cache',
    r'C:\Users\abhra\AppData\Local\Google\Chrome\User Data\Default\Cache',
    r'C:\Users\abhra\AppData\Local\Google\Chrome\User Data\Default\Code Cache',
    r'C:\Users\abhra\AppData\Local\Temp',
    r'C:\Users\abhra\AppData\Local\EpicGamesLauncher\Saved\Logs',
    r'C:\Users\abhra\AppData\Local\Steam\htmlcache',
    r'C:\Users\abhra\AppData\Roaming\kingsoft\office6\log',
    r'C:\Users\abhra\AppData\Local\Epic Games\EOSOverlay\BrowserCache',
    r'C:\Users\abhra\AppData\Roaming\Code\Partitions\vscode-browser\Code Cache',
    r'C:\Users\abhra\.claude\downloads',
    r'C:\Users\abhra\.nuget\packages',
]
for p in VETO_MUST_NOT:
    check('veto allows %s' % p.split('\\')[-1], not sc.safety_veto(p)[0])

check('veto is independent of the model score',
      sc.safety_veto(r'C:\Users\abhra\AppData\Roaming\Microsoft\Windows\Recent')[0] and
      sc.ai_score(r'C:\Users\abhra\AppData\Roaming\Microsoft\Windows\Recent', 12e6, 40, M) >= 0.0)
check('walk_blocked stops at protected roots',
      sc.walk_blocked(r'C:\Users\abhra\Documents\x'))
check('walk_blocked allows traversal of a state folder with cache children',
      not sc.walk_blocked(r'C:\Users\abhra\AppData\Local\Epic Games\EOSOverlay'))

print('=== v9 cache name matching ===')
for name in ('Cache', 'GPUCache', 'Code Cache', 'BrowserCache', 'SharedClientCache',
             'htmlcache', 'webcache_4430', 'logs', 'Temp', 'ShaderCache'):
    check('cache_name_match(%s)' % name, sc.cache_name_match(name))
for name in ('Documents', 'src', 'bin', 'Recent', 'Themes', 'settings', 'LocalState'):
    check('cache_name_match rejects %s' % name, not sc.cache_name_match(name))

print('=== v9 discovery coverage (the 1.67 GB safe mode used to miss) ===')
targets = sc.build_targets()
hunt_paths = {os.path.normcase(p) for l, p, f in targets if l.startswith('hunt ')}
DISCOVERY = [
    r'C:\Users\abhra\AppData\Local\Epic Games\EOSOverlay\BrowserCache',
    r'C:\Users\abhra\AppData\Roaming\com.qoder.app.stable\Code Cache',
    r'C:\Users\abhra\AppData\Roaming\com.qoder.app.stable\Cache',
    r'C:\Users\abhra\AppData\Roaming\Code\Partitions\vscode-browser\Code Cache',
    r'C:\Users\abhra\AppData\Local\Steam\htmlcache',
    r'C:\Users\abhra\AppData\Roaming\kingsoft\office6\log',
    r'C:\Users\abhra\AppData\Local\EpicGamesLauncher\Saved\Logs',
]
for p in DISCOVERY:
    if not os.path.isdir(p):
        # the cleaner deletes these caches; a cleaned-away folder cannot be
        # discovered. The check stays meaningful for whenever the app
        # recreates the folder.
        print('  SKIP  discovery check (already cleaned away): %s' % p.split('\\')[-1])
        continue
    check('safe-mode discovery finds %s' % p.split('\\')[-1], os.path.normcase(p) in hunt_paths)
check('safe-mode discovery found a meaningful number of dirs', len(hunt_paths) > 50)

print('=== v9 no target escapes into protected territory ===')
all_targets = [p for l, p, f in targets if p]
def under(p, base):
    n = os.path.normcase(os.path.abspath(p))
    b = os.path.normcase(os.path.abspath(base))
    return n == b or n.startswith(b + os.sep)
PROTECTED_BASES = [os.path.join(sc.HOME, d) for d in
                   ('Downloads', 'Documents', 'Pictures', 'Videos', 'Desktop', 'OneDrive')]
PROTECTED_BASES += [os.path.join(sc.LOCAL, 'Programs'), os.path.join(sc.LOCAL, 'Packages'),
                    os.path.join(sc.HOME, '.ssh'), os.path.join(sc.HOME, '.aws')]
escaped = [p for p in all_targets if any(under(p, b) for b in PROTECTED_BASES)]
check('no target inside protected territory (%d escaped)' % len(escaped), not escaped)

print('=== v9.1 old-Windows targets (DEEP tier) ===')
_deep, _full, _aggr = sc.DEEP, sc.FULL, sc.AGGRESSIVE
sc.DEEP = sc.FULL = True
sc.AGGRESSIVE = False
try:
    deep_targets = sc.build_targets()
finally:
    sc.DEEP, sc.FULL, sc.AGGRESSIVE = _deep, _full, _aggr
deep_labels = [t[0] for t in deep_targets]
need_v91 = ['old windows (windows.old)', 'setup leftover (~bt)', 'setup leftover (~ws)',
            'setup leftover (getcurrent)', 'reset leftover (sysreset)',
            'winre update leftover', 'windows update logs']
for n in need_v91:
    check('deep target present: %s' % n, n in deep_labels)
check('windows.old NOT in SAFE mode', 'old windows (windows.old)' not in labels)
check('windows update logs NOT in SAFE mode', 'windows update logs' not in labels)
deep_fns = {l: f for l, p, f in deep_targets}
check('windows.old is a whole-dir privileged delete',
      getattr(deep_fns.get('old windows (windows.old)'), 'whole_dir', None) is True)

print('=== v9.1 hunter never touches Python user packages ===')
check('site-packages matched by hunter skip rule',
      bool(sc.HUNTER_SKIP.search(r'C:\Users\abhra\AppData\Roaming\Python\Python311\site-packages')))
check('pycache INSIDE site-packages is skipped',
      bool(sc.HUNTER_SKIP.search(
          r'C:\Users\abhra\AppData\Roaming\Python\Python311\site-packages\requests\__pycache__')))
check('Python313 variant also skipped',
      bool(sc.HUNTER_SKIP.search(r'C:\Users\abhra\AppData\Local\Python\Python313\site-packages\x')))
check('unrelated Python-named cache dir not skipped',
      not sc.HUNTER_SKIP.search(r'C:\Users\abhra\AppData\Local\SomeApp\Python\cache'))
check('uv tool env site-packages skipped (propcache package)',
      bool(sc.HUNTER_SKIP.search(
          r'C:\Users\abhra\AppData\Roaming\uv\tools\kimi-cli\Lib\site-packages\propcache')))
hunt_paths_v91 = [p for l, p, f in deep_targets if l.startswith('hunt ')]
check('no hunt target inside any site-packages (%d hunt targets)'
      % len(hunt_paths_v91),
      not any('site-packages' in p for p in hunt_paths_v91))

print('=== v9.1 veto allowlist ===')
check('veto allows C:\\Windows.old', not sc.safety_veto(r'C:\Windows.old')[0])
check('veto allows C:\\$WinREAgent', not sc.safety_veto(r'C:\$WinREAgent')[0])
check('allowlist is exact path only (subpath still vetoed)',
      sc.safety_veto(r'C:\Windows.old\Recent')[0])
check('hunter cannot name-match Windows.old', not sc.cache_name_match('Windows.old'))
check('hunter cannot name-match $WinREAgent', not sc.cache_name_match('$WinREAgent'))

print('=== v9.1 power parsing ===')
canned = ('Power Setting GUID: be337238-0d82-4146-a960-4f3749d470c7'
          ' (Processor performance boost mode)\n'
          '    Current AC Power Setting Index: 0x00000002\n'
          '    Current DC Power Setting Index: 0x00000000\n')
ac, dc = sc.parse_power_indexes(canned)
check('parse AC boost index 2', ac == 2)
check('parse DC boost index 0 (disabled)', dc == 0)
ac2, dc2 = sc.parse_power_indexes('')
check('empty powercfg output parses to None', ac2 is None and dc2 is None)
check('boost 0 name explains the slowdown', 'base clock' in sc.BOOST_MODES[0])
import io, contextlib
_buf = io.StringIO()
with contextlib.redirect_stdout(_buf):
    sc.performance_report()
check('performance_report runs end to end', 'Power scheme' in _buf.getvalue())

print('=== v9 speed ===')
t_scan = time.time()
sc.build_targets()
scan_secs = time.time() - t_scan
check('build_targets under 20s (%.1fs)' % scan_secs, scan_secs < 20.0)
t_sz = time.time()
sc.dir_size(sc.LOCAL)
sz_secs = time.time() - t_sz
check('dir_size on AppData\\Local under 30s (%.1fs)' % sz_secs, sz_secs < 30.0)

print('\n=== RESULTS: %d passed, %d failed ===' % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
