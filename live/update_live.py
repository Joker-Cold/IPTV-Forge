"""
One-click live update: run iptv_api once, regroup the result, publish it.

    1. make sure Docker is up (starts Docker Desktop if it is not)
    2. recreate the iptv-api container - with update_startup=True it runs one
       full fetch + speed test on boot - and wait for its "更新完成" log line
    3. stop the container again, so it does not re-run on its own schedule
    4. post_classify: ../iptv_api/output/cold_result.m3u -> output/COLD_result.m3u
    5. copy to ../../HK-IPTV/COLD_OK.m3u8
       (commit / push over there is left to you)

Usage:  python update_live.py [--no-docker] [--no-publish] [--keep-running] [--force]
    --no-docker     skip 1-3, regroup whatever iptv_api produced last
    --no-publish    stop after step 4
    --keep-running  leave the container up after the run
    --force         publish even if the channel count dropped by more than half
"""
import configparser
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse

import post_classify as PC

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
API_DIR = os.path.join(ROOT, 'iptv_api')
COMPOSE = os.path.join(API_DIR, 'docker-compose.yml')
USER_CONFIG = os.path.join(API_DIR, 'config', 'user_config.ini')
CONTAINER = 'iptv-api'
DOCKER_DESKTOP = os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'),
                              'Docker', 'Docker', 'Docker Desktop.exe')

PUBLISH_DIR = os.path.normpath(os.path.join(ROOT, '..', 'HK-IPTV'))
PUBLISH_FILE = os.path.join(PUBLISH_DIR, 'COLD_OK.m3u8')

RUN_TIMEOUT = 90 * 60     # a normal run takes ~15 min
POLL = 20

DONE = ('更新完成', 'Update completed')
CANCELLED = ('更新已被取消', 'Update has been cancelled')
# group title iptv_api stamps on a result written mid-run
RUNNING = ('正在更新中', 'Update in progress')
# last tqdm bar in the log, e.g. "🚀 测速:  22% 148/664 ["
PROGRESS = re.compile(r'(\d+)%\s*(\d+)/(\d+)\s*\[')


def fail(msg):
    print(f'\n[ERROR] {msg}')
    sys.exit(1)


def docker_ok():
    return subprocess.run(['docker', 'info'], capture_output=True).returncode == 0


def ensure_docker():
    if docker_ok():
        return
    if not os.path.exists(DOCKER_DESKTOP):
        fail('Docker 没在运行，也找不到 Docker Desktop')
    print('[INFO] 启动 Docker Desktop ...')
    subprocess.Popen([DOCKER_DESKTOP])
    deadline = time.time() + 180
    while time.time() < deadline:
        time.sleep(5)
        if docker_ok():
            return
    fail('等了 3 分钟 Docker 还没起来')


def check_proxy():
    """iptv_api fetches subscriptions through the host proxy in user_config.ini.
    If that is down the run still finishes, just with far fewer sources."""
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(USER_CONFIG, encoding='utf-8')
    proxy = cp.get('Settings', 'http_proxy', fallback='').strip()
    port = urllib.parse.urlsplit(proxy).port if proxy else None
    if not port:
        return
    try:
        socket.create_connection(('127.0.0.1', port), timeout=2).close()
    except OSError:
        print(f'[WARN] 代理 127.0.0.1:{port} 连不上，订阅源会抓取失败，'
              f'结果只剩本地源 + 历史源')


def container_logs():
    out = subprocess.run(['docker', 'logs', CONTAINER], capture_output=True).stdout
    return out.decode('utf-8', 'replace')


def container_running():
    r = subprocess.run(['docker', 'inspect', '-f', '{{.State.Running}}', CONTAINER],
                       capture_output=True, text=True)
    return r.stdout.strip() == 'true'


def compose(*args):
    subprocess.run(['docker', 'compose', '-f', COMPOSE, *args], check=True)


def run_container(keep_running):
    started = time.time()
    compose('up', '-d', '--force-recreate')
    try:
        last = None
        while True:
            time.sleep(POLL)
            logs = container_logs()
            if any(s in logs for s in DONE):
                break
            if any(s in logs for s in CANCELLED):
                fail('iptv_api 报告更新被取消')
            if not container_running():
                tail = '\n'.join(logs.splitlines()[-20:])
                fail(f'容器中途退出了，最后的日志：\n{tail}')
            if time.time() - started > RUN_TIMEOUT:
                fail(f'{RUN_TIMEOUT // 60} 分钟还没跑完，放弃')
            bars = PROGRESS.findall(logs)
            if bars and bars[-1] != last:
                last = bars[-1]
                pct, n, total = last
                print(f'[INFO] 进度 {pct}% ({n}/{total})  已用 {int(time.time() - started) // 60} 分钟')
        print(f'[INFO] iptv_api 更新完成，用时 {int(time.time() - started) // 60} 分钟')
    finally:
        if not keep_running:
            compose('stop')

    if os.path.getmtime(PC.DEFAULT_SRC) < started:
        fail(f'{PC.DEFAULT_SRC} 没有被这次运行更新')


def count_entries(path):
    with open(path, encoding='utf-8') as f:
        return sum(1 for line in f if line.startswith('#EXTINF'))


def publish(force):
    if not os.path.isdir(PUBLISH_DIR):
        fail(f'找不到发布目录 {PUBLISH_DIR}')
    with open(PC.DEFAULT_SRC, encoding='utf-8') as f:
        head = f.read(4096)
    if any(s in head for s in RUNNING) and not force:
        fail('iptv_api 的结果是跑到一半的中间版（「正在更新中」），没有发布')
    new = count_entries(PC.DEFAULT_DST)
    old = count_entries(PUBLISH_FILE) if os.path.exists(PUBLISH_FILE) else 0
    print(f'[INFO] 频道条目：新 {new} / 当前发布 {old}')
    if new < old / 2 and not force:
        fail('比当前发布版少了一半以上，像是抓取或测速出了问题，没有发布。'
             '确认没问题的话加 --force 重跑')
    shutil.copyfile(PC.DEFAULT_DST, PUBLISH_FILE)
    print(f'[INFO] 已复制到 {PUBLISH_FILE}，记得去那边 commit + push')


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    args = set(sys.argv[1:])
    unknown = args - {'--no-docker', '--no-publish', '--keep-running', '--force'}
    if unknown:
        fail(f'未知参数 {" ".join(sorted(unknown))}\n{__doc__}')

    if '--no-docker' not in args:
        ensure_docker()
        check_proxy()
        run_container('--keep-running' in args)

    os.makedirs(os.path.dirname(PC.DEFAULT_DST), exist_ok=True)
    PC.process(PC.DEFAULT_SRC, PC.DEFAULT_DST)

    if '--no-publish' not in args:
        publish('--force' in args)


if __name__ == '__main__':
    main()
