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
check('model arch is mlp + brain v7/v8', M.get('arch') == 'mlp' and M.get('brain') in ('v7', 'v8'))
check('two hidden layers [192, 48]', M.get('hidden') == [192, 48])
check('holdout accuracy >= 0.90', M.get('holdout_accuracy', 0) >= 0.90)
check('trained on mixed real+synth >= 8000', M.get('samples', 0) >= 8000)
check('hash dims 512 + 20 extras', M.get('hash_dims') == 512 and M.get('dims') == 532)
check('beats or matches previous brain',
      M.get('prev_holdout_accuracy') is None or
      (M['holdout_accuracy'] >= M['prev_holdout_accuracy'] - 0.01 and
       M['holdout_f1'] >= M['prev_holdout_f1'] - 0.01))

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
check('kb brain v7/v8', KB.get('brain') in ('v7', 'v8'))
check('learned tokens > 10', len(KB['learned_junk_tokens']) > 10)
top = KB['learned_junk_tokens'][0]
check('top token junk_rate >= 0.8 (%s %.2f)' % (top['token'], top['junk_rate']),
      top['junk_rate'] >= 0.8)

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

print('\n=== RESULTS: %d passed, %d failed ===' % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
