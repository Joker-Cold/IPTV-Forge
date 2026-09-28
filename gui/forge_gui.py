# -*- coding: utf-8 -*-
"""
IPTV-Forge desktop app: a pywebview window (the page lives in gui/ui/) over
the pipeline scripts. Every button runs the scripts the README describes
(live/update_live.py, vod/*.py, git in ../HK-IPTV) as child processes and
streams their output into the page, so the scripts stay the single source of
truth and keep working from the command line on their own.

    python gui/forge_gui.py     needs pip install pywebview
    IPTV-Forge.exe              built by gui/build_exe.bat, needs nothing;
                                published in GitHub Releases, not committed

The exe bundles Python and everything the scripts import, and runs each script
as `IPTV-Forge.exe --run <script> [args]`. It still has to sit in the repo
root: live/, vod/ and iptv_api/ are read and written in place.
"""
import configparser
import ctypes
import datetime
import json
import os
import re
import runpy
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse

TITLE = 'IPTV-Forge'
FROZEN = getattr(sys, 'frozen', False)
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def run_script(argv):
    """`IPTV-Forge.exe --run script.py [args]`: the exe standing in for
    python.exe, so the scripts run on the Python bundled inside it."""
    script = os.path.abspath(argv[0])
    sys.argv = [script, *argv[1:]]
    sys.path.insert(0, os.path.dirname(script))
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    runpy.run_path(script, run_name='__main__')


def find_root():
    """The folder holding live/ and vod/, searched upward from this file - or
    from the exe, so a frozen build works in the repo root and in dist/."""
    d = os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))
    for _ in range(3):
        if os.path.isfile(os.path.join(d, 'live', 'update_live.py')):
            return d
        d = os.path.dirname(d)
    return None


def die(msg):
    ctypes.windll.user32.MessageBoxW(None, msg, TITLE, 0x10)
    sys.exit(1)


ROOT = find_root() or die('找不到 live\\ 和 vod\\ 目录。\n\n'
                          '请从 Releases 下载完整包 IPTV-Forge-windows.zip，解压后双击里面的 '
                          'IPTV-Forge.exe；或者把 IPTV-Forge.exe 放进 git clone 下来的仓库根目录。')
# started through pythonw: the scripts still get the console interpreter
_console = os.path.join(os.path.dirname(sys.executable), 'python.exe')
PYTHON = sys.executable if FROZEN or not os.path.exists(_console) else _console
UI = os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__))), 'ui')

LIVE = os.path.join(ROOT, 'live')
API_CONFIG = os.path.join(ROOT, 'iptv_api', 'config')
COMPOSE = os.path.join(ROOT, 'iptv_api', 'docker-compose.yml')
CONTAINER = 'iptv-api'
LIVE_RESULT = os.path.join(LIVE, 'output', 'COLD_result.m3u')
PUBLISH_DIR = os.path.normpath(os.path.join(ROOT, '..', 'HK-IPTV'))
LIVE_PUBLISHED = os.path.join(PUBLISH_DIR, 'COLD_OK.m3u8')

VOD = os.path.join(ROOT, 'vod')
VP = runpy.run_path(os.path.join(VOD, 'paths.py'))    # vod's own path table

CHILD_ENV = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1',
                 # fail instead of waiting forever on a prompt nobody can see
                 GIT_TERMINAL_PROMPT='0')

LIVE_FLAGS = ('--no-docker', '--no-publish', '--keep-running', '--force')
# update_live.py's phases, and the log line that shows each one has begun
LIVE_STAGES = [
    ('启动 Docker', None),
    ('抓取 + 测速', r'Container \S+\s+(Started|Running)|\[INFO\] 进度'),
    ('重新分组', r'更新完成|iptv-org channels'),
    ('发布', r'频道条目'),
]


def py(script, *args):
    """argv that runs one of the pipeline scripts."""
    if FROZEN:
        return [sys.executable, '--run', script, *args]
    return [PYTHON, '-u', script, *args]


VOD_STEPS = [   # (key, stepper label, full label, argv)
    ('1', '探测候选', '探测候选 candidates.json', py(os.path.join(VOD, 'verify_candidates.py'))),
    ('1b', '探测补充', '探测候选 harvest.json', py(os.path.join(VOD, 'verify_candidates.py'),
                                                  VP['HARVEST'], '-o', VP['REPORT2'])),
    ('2', '去重', '合并、按内容去重', py(os.path.join(VOD, 'build_final.py'))),
    ('3', '报告', '生成验证报告', py(os.path.join(VOD, 'make_report.py'))),
    ('4', '解码', '解码每个仓', py(os.path.join(VOD, 'decode_configs.py'))),
    ('5', '精选 12', '选出 12 个精选', py(os.path.join(VOD, 'select_12.py'))),
    ('6', '复查', '复查精选是否在线', py(os.path.join(VOD, 'verify_selected.py'))),
    ('7', '生成配置', '生成 Cold_Movie.json', py(os.path.join(VOD, 'update_cold_movie.py'))),
]

# a log line gets the colour of the first pattern it matches
LINE_TAGS = [
    ('error', re.compile(r'\[ERROR\]|Traceback|Error\b|\[DEAD\]|❌|^\s*dead\s')),
    ('warn', re.compile(r'\[WARN\]|WARNING|^\s*dup\s')),
    ('good', re.compile(r'\[OK\]|^\s*KEEP\s|完成|已复制到|^wrote ')),
]
# "[INFO] 进度 22% (148/664)" from update_live, "  probed 25/200" from verify_candidates
PROGRESS = re.compile(r'进度 (\d+)%|probed (\d+)/(\d+)')


# ---------------------------------------------------------------- helpers

def show_cmd(argv):
    """argv for the log: the interpreter as `python`, repo paths relative."""
    if argv[0] in (sys.executable, PYTHON) and len(argv) > 1 and argv[1] in ('-u', '--run'):
        argv = ['python', *argv[2:]]
    out = []
    for a in argv:
        if os.path.isabs(a) and a.startswith(ROOT):
            a = os.path.relpath(a, ROOT)
        out.append('"%s"' % a if ' ' in a else a)
    return ' '.join(out)


def rel(path):
    return os.path.relpath(path, ROOT).replace('\\', '/')


def elapsed(seconds):
    m, s = divmod(int(seconds), 60)
    return '%d:%02d' % (m, s)


def stamp(path):
    if not os.path.exists(path):
        return None
    t = datetime.datetime.fromtimestamp(os.path.getmtime(path))
    return t.strftime('%Y-%m-%d %H:%M')


def live_product():
    """What a live run leaves behind: the published copy if this checkout
    publishes to HK-IPTV, else the local result."""
    return LIVE_PUBLISHED if os.path.isdir(PUBLISH_DIR) else LIVE_RESULT


def m3u_groups(path):
    """[[group, channels], ...] in file order, without the timestamp group."""
    counts = {}
    if os.path.exists(path):
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                if line.startswith('#EXTINF'):
                    m = re.search(r'group-title="([^"]*)"', line)
                    # drop the leading emoji / flag, the page can't draw flags
                    g = re.sub(r'^[^\w一-鿿]+', '', m.group(1) if m else '') or '未分组'
                    counts[g] = counts.get(g, 0) + 1
    counts.pop('更新时间', None)
    return [[g, n] for g, n in counts.items()]


def m3u_count(path):
    return sum(n for _, n in m3u_groups(path))


def cold_movie_count(path):
    """(active, commented-out) entries of a Cold_Movie.json-style file."""
    active = dead = 0
    if os.path.exists(path):
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                s = line.strip()
                if s.startswith('"url"'):
                    active += 1
                elif s.startswith('//') and '"url"' in s:
                    dead += 1
    return active, dead


def read_picks():
    picks = []
    if os.path.exists(VP['SELECTED']):
        with open(VP['SELECTED'], encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    p = json.loads(line)
                    picks.append({'rank': p.get('rank'), 'url': p['url'],
                                  'name': re.sub(r'^[🚀\d\-]+', '', p['name'])})
    return picks


def count_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            return len(json.load(f))
    except (OSError, ValueError):
        return 0


def proxy_port():
    """Port of the host proxy iptv_api fetches subscriptions through."""
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(os.path.join(API_CONFIG, 'user_config.ini'), encoding='utf-8')
    proxy = cp.get('Settings', 'http_proxy', fallback='').strip()
    return urllib.parse.urlsplit(proxy).port if proxy else None


def compose(*args):
    return ['docker', 'compose', '-f', COMPOSE, *args]


def open_targets():
    cfg = lambda name: os.path.join(API_CONFIG, name)
    return {
        'subscribe': cfg('subscribe.txt'), 'demo': cfg('user_demo.txt'),
        'alias': cfg('alias.txt'), 'config': cfg('user_config.ini'), 'epg': cfg('epg.txt'),
        'live_sources': os.path.join(LIVE, 'sources'), 'live_output': os.path.join(LIVE, 'output'),
        'live_product': live_product(), 'publish_dir': PUBLISH_DIR,
        'candidates': VP['CANDIDATES'], 'harvest': VP['HARVEST'],
        'jiekou': os.path.join(VP['SOURCES'], '接口.txt'),
        'report': VP['VERIFY_REPORT'], 'selected': VP['SELECTED'], 'cold_movie': VP['COLD_MOVIE'],
        'vod_data': VP['DATA'], 'vod_output': VP['OUTPUT'], 'root': ROOT,
    }


# ---------------------------------------------------------------- runner

class Runner:
    """One page's worker: runs one list of steps at a time and keeps the log
    and progress the page polls for. A step is (title, argv), run as a child
    process with its output streamed into the log, or (title, fn), called as
    fn(log) in the worker. The first failing step ends the list.

    The job's stages are its steps (named by `stages`, else by the step
    titles); with `markers` they are phases of one step instead, and stage i
    begins at the first log line matching markers[i]."""

    MAX_LINES = 5000

    def __init__(self):
        self.lock = threading.Lock()
        self.lines = []          # (seq, text, tag)
        self.seq = 0
        self.running = False
        self.cancelled = False
        self.proc = None
        self.job = None

    def log(self, text, tag=None):
        job = self.job
        if tag is None:
            tag = next((name for name, rx in LINE_TAGS if rx.search(text)), '')
            if job and job['markers']:
                for i, rx in enumerate(job['markers']):
                    if rx and i > job['stage'] and rx.search(text):
                        job['stage'], job['progress'] = i, None
            m = job and PROGRESS.search(text)
            if m:
                pct, n, total = m.groups()
                job['progress'] = int(pct) / 100 if pct else int(n) / int(total)
        with self.lock:
            self.seq += 1
            self.lines.append((self.seq, text, tag))
            del self.lines[:-self.MAX_LINES]

    def clear(self):
        with self.lock:
            self.lines = []

    def snapshot(self, since):
        with self.lock:
            lines = [l for l in self.lines if l[0] > since]
            seq = self.seq
        job = self.job
        out = {'seq': seq, 'lines': lines, 'running': self.running, 'job': None}
        if job:
            out['job'] = {k: job[k] for k in ('title', 'stages', 'stage', 'progress', 'state')}
            out['job']['elapsed'] = int((job['ended'] or time.time()) - job['started'])
        return out

    def run(self, title, steps, stages=None, markers=None, done=None):
        with self.lock:
            if self.running:
                return False
            self.running, self.cancelled = True, False
        self.job = {'title': title, 'stages': stages or [t for t, _ in steps],
                    'markers': [re.compile(m) if m else None for m in markers or []],
                    'stage': 0, 'progress': None, 'state': 'running',
                    'started': time.time(), 'ended': None}
        threading.Thread(target=self.work, args=(steps, not markers, done),
                         daemon=True).start()
        return True

    def work(self, steps, per_step, done):
        job, ok = self.job, True
        for i, (title, cmd) in enumerate(steps):
            if self.cancelled:
                ok = False
                break
            if per_step:
                job['stage'], job['progress'] = i, None
            self.log('\n▶ %s    %s\n' % (title, time.strftime('%H:%M:%S')), 'head')
            try:
                if callable(cmd):
                    cmd(self.log)
                    continue
                rc = self.spawn(cmd)
            except Exception as e:
                self.log('[ERROR] %s: %s\n' % (type(e).__name__, e))
                ok = False
                break
            if rc != 0:
                self.log('[ERROR] 已停止\n' if self.cancelled else
                         '[ERROR] 退出码 %d，后面的步骤不再执行\n' % rc)
                ok = False
                break
        job['ended'] = time.time()
        if ok:
            job['stage'], job['progress'] = len(job['stages']), None
            self.log('✔ 完成，用时 %s\n' % elapsed(job['ended'] - job['started']), 'good')
        job['state'] = 'done' if ok else 'stopped' if self.cancelled else 'failed'
        self.running = False
        if done:
            done(ok)

    def spawn(self, argv):
        self.log('$ %s\n' % show_cmd(argv), 'cmd')
        self.proc = subprocess.Popen(argv, cwd=ROOT, env=CHILD_ENV,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        if self.cancelled:       # 停止 was clicked while this was starting
            self.kill()
        for raw in iter(self.proc.stdout.readline, b''):
            # progress bars redraw with \r: keep only their last state
            line = raw.rstrip(b'\r\n').rsplit(b'\r', 1)[-1]
            self.log(line.decode('utf-8', 'replace') + '\n')
        rc = self.proc.wait()
        self.proc = None
        return rc

    def stop(self):
        if self.running:
            self.cancelled = True
            self.kill()

    def kill(self):
        p = self.proc
        if p and p.poll() is None:
            # /T takes the docker / git processes the script started with it
            subprocess.run(['taskkill', '/PID', str(p.pid), '/T', '/F'],
                           capture_output=True, creationflags=NO_WINDOW)


# ---------------------------------------------------------------- api

class Api:
    """What the page calls as window.pywebview.api.<name>(...). Actions return
    {} on success or {'error': message}. pywebview exposes every public
    attribute, hence the underscores on the state."""

    def __init__(self):
        self._runners = {'live': Runner(), 'vod': Runner()}
        self._window = None
        self._live_docker = False     # the live run in progress brings the container up
        self._live_keep = False

    def _start(self, page, title, steps, **kw):
        if not self._runners[page].run(title, steps, **kw):
            return {'error': '这一页还有任务在运行，等它结束或先点「停止」'}
        return {}

    # ---------- read

    def info(self):
        return {
            'root': ROOT,
            'publish_dir': PUBLISH_DIR,
            'has_publish': os.path.isdir(PUBLISH_DIR),
            'can_push': bool(os.path.isdir(os.path.join(PUBLISH_DIR, '.git')) and shutil.which('git')),
            'frozen': FROZEN,
            'live_stages': [n for n, _ in LIVE_STAGES],
            'vod_steps': [{'key': k, 'short': short, 'label': label}
                          for k, short, label, _ in VOD_STEPS],
            'check_default': VP['COLD_MOVIE'],
        }

    def stats(self):
        product = live_product()
        active, dead = cold_movie_count(VP['COLD_MOVIE'])
        return {
            'live': {'groups': m3u_groups(product), 'time': stamp(product), 'file': rel(product)},
            'vod': {'active': active, 'dead': dead, 'time': stamp(VP['COLD_MOVIE']),
                    'file': rel(VP['COLD_MOVIE']), 'picks': read_picks(),
                    'candidates': count_json(VP['CANDIDATES']) + count_json(VP['HARVEST'])},
        }

    def env(self):
        """Slow (docker info): the page asks for it separately."""
        docker = shutil.which('docker')
        running = False
        if docker:
            try:
                running = subprocess.run(['docker', 'info'], capture_output=True, timeout=20,
                                         creationflags=NO_WINDOW).returncode == 0
            except subprocess.TimeoutExpired:
                pass
        port = proxy_port()
        proxy_ok = False
        if port:
            try:
                socket.create_connection(('127.0.0.1', port), timeout=2).close()
                proxy_ok = True
            except OSError:
                pass
        return {'docker': bool(docker), 'docker_running': running,
                'proxy_port': port, 'proxy_ok': proxy_ok}

    def poll(self, page, since):
        return self._runners[page].snapshot(since)

    def clear(self, page):
        self._runners[page].clear()

    # ---------- actions

    def open(self, key):
        path = open_targets().get(key)
        if not path or not os.path.exists(path):
            return {'error': '还不存在，先运行一次：%s' % (path and rel(path))}
        try:
            os.startfile(path)
        except OSError:
            # nothing associated with the extension (.json / .ini on a bare system)
            subprocess.Popen(['notepad.exe', path])
        return {}

    def pick_file(self):
        import webview
        start = os.path.dirname(VP['COLD_MOVIE'])
        got = self._window.create_file_dialog(
            webview.FileDialog.OPEN, directory=start,
            file_types=('多仓文件 (*.json;*.txt)', '所有文件 (*.*)'))
        return got[0] if got else None

    def stop(self, page):
        self._runners[page].stop()

    def live_update(self, flags):
        flags = [f for f in LIVE_FLAGS if f in flags]
        if not os.path.isdir(PUBLISH_DIR) and '--no-publish' not in flags:
            flags.append('--no-publish')    # no HK-IPTV here: the result stays in live/output
        stages = LIVE_STAGES[2:] if '--no-docker' in flags else LIVE_STAGES
        if '--no-publish' in flags:
            stages = stages[:-1]
        self._live_docker = '--no-docker' not in flags
        self._live_keep = '--keep-running' in flags
        argv = py(os.path.join(LIVE, 'update_live.py'), *flags)
        return self._start('live', '更新直播', [('更新直播', argv)],
                           stages=[n for n, _ in stages], markers=[m for _, m in stages],
                           done=self._live_done)

    def _live_done(self, ok):
        docker, self._live_docker = self._live_docker, False
        # a killed update_live.py never reaches its own `compose stop`, and the
        # container would go on to re-run on its 12-hour schedule
        if self._runners['live'].cancelled and docker and not self._live_keep:
            self._runners['live'].run('停止容器', [('停止容器', compose('stop'))])

    def live_docker(self, action):
        steps = {
            'logs': ('容器日志', ['docker', 'logs', '--tail', '60', CONTAINER]),
            'stop': ('停止容器', compose('stop')),
            'pull': ('更新镜像', compose('pull')),
        }[action]
        return self._start('live', steps[0], [steps])

    def vod_run(self, keys, fresh):
        steps, stages = [], []
        for key, short, label, argv in VOD_STEPS:
            if key not in keys:
                continue
            if key == '4' and fresh:
                steps.append(('清空下载缓存', self._clear_cache))
                stages.append('清缓存')
            steps.append(('%s. %s' % (key, label), argv))
            stages.append(short)
        if not steps:
            return {'error': '先勾选要跑的步骤'}
        return self._start('vod', '点播筛选', steps, stages=stages)

    @staticmethod
    def _clear_cache(log):
        shutil.rmtree(VP['CACHE'], ignore_errors=True)
        log('已删除 %s\n' % rel(VP['CACHE']))

    def vod_check(self, path, proxy):
        path = (path or '').strip()
        if not os.path.isfile(path):
            return {'error': '文件不存在：%s' % path}
        argv = py(os.path.join(VOD, 'check_tvbox_sources.py'), path)
        if (proxy or '').strip():
            argv += ['--proxy', proxy.strip()]
        return self._start('vod', '体检', [('体检 %s' % os.path.basename(path), argv)])

    # ---------- publishing (only offered when ../HK-IPTV is a git checkout)

    def git_prepare(self, page):
        """What 提交并推送 would do: {file, changed, message} or {error}."""
        filename = 'COLD_OK.m3u8' if page == 'live' else 'Cold_Movie.json'
        try:
            st = subprocess.run(['git', '-C', PUBLISH_DIR, 'status', '--porcelain', '--', filename],
                                capture_output=True, text=True, encoding='utf-8',
                                errors='replace', creationflags=NO_WINDOW)
        except OSError:
            return {'error': '找不到 git'}
        if st.returncode:
            return {'error': st.stderr.strip() or 'git status 失败'}
        today = datetime.date.today()
        if page == 'live':
            message = '直播更新 %s：%d 条' % (today, m3u_count(LIVE_PUBLISHED))
        else:
            message = '点播更新 %s：%d 个仓' % (today, cold_movie_count(VP['COLD_MOVIE'])[0])
        return {'file': filename, 'changed': bool(st.stdout.strip()), 'message': message}

    def git_publish(self, page, message):
        """add + commit + push the page's file; with no message, just push."""
        filename = 'COLD_OK.m3u8' if page == 'live' else 'Cold_Movie.json'
        git = ['git', '-C', PUBLISH_DIR]
        steps = [('git push', git + ['push'])]
        if (message or '').strip():
            steps[:0] = [('git add', git + ['add', '--', filename]),
                         ('git commit', git + ['commit', '-m', message.strip(), '--', filename])]
        return self._start(page, '发布到 GitHub', steps)

    # ---------- window

    def _closing(self):
        busy = [r for r in self._runners.values() if r.running]
        if busy and not self._window.create_confirmation_dialog(
                TITLE, '还有任务在运行，退出会中止它。确定退出？'):
            return False
        for r in busy:
            r.stop()
        if busy and self._live_docker and not self._live_keep:
            subprocess.Popen(compose('stop'), creationflags=NO_WINDOW,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True


def main():
    import webview
    api = Api()
    # centred, and on a small or zoomed screen no bigger than it (minus the taskbar)
    screen = webview.screens[0]
    w, h = min(1320, screen.width - 80), min(900, screen.height - 110)
    window = webview.create_window(TITLE, os.path.join(UI, 'index.html'), js_api=api,
                                   width=w, height=h, min_size=(min(1080, w), min(720, h)),
                                   x=screen.x + (screen.width - w) // 2,
                                   y=screen.y + max(0, (screen.height - h) // 2 - 24),
                                   background_color='#F3F6FB')
    api._window = window
    window.events.closing += api._closing
    # keep the page's localStorage (the theme choice) between runs
    storage = os.path.join(os.environ.get('LOCALAPPDATA', ROOT), TITLE)
    webview.start(http_server=True, private_mode=False, storage_path=storage,
                  icon=os.path.join(UI, 'icon.ico'), debug=bool(os.environ.get('IPTV_FORGE_DEBUG')))


if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[1] == '--run':
        run_script(sys.argv[2:])
    else:
        main()
