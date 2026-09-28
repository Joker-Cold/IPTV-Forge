# -*- coding: utf-8 -*-
"""
Build IPTV-Forge.exe into the repo root:  python gui/build_exe.py [--zip]
(or double-click gui/build_exe.bat). Needs pip install pyinstaller pywebview.

--zip also packs what goes up to GitHub Releases, into release/:
    IPTV-Forge-windows.zip   the committed tree + the exe: unzip, double-click
    IPTV-Forge.exe           on its own, for a git clone
The zip is made with `git archive HEAD`, so ignored files (paid sources,
local notes) and uncommitted changes never get in - commit first.

The exe runs the pipeline scripts on its own bundled Python (run_script in
forge_gui.py), so it has to carry every module they import. forge_gui never
imports them itself, so PyInstaller can't see them: this scans live/*.py and
vod/*.py and passes each import as --hidden-import. The scripts themselves are
not bundled - the exe runs them from disk, so editing one needs no rebuild.
"""
import ast
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT_DIRS = [os.path.join(ROOT, 'live'), os.path.join(ROOT, 'vod')]
EXE = os.path.join(ROOT, 'IPTV-Forge.exe')
RELEASE = os.path.join(ROOT, 'release')


def module_name(name):
    """The real name of module `name`, or None if it isn't one (`from m import
    func`). Aliases resolve: requests.packages.urllib3 is really urllib3."""
    try:
        return importlib.import_module(name).__name__
    except ImportError:
        return None


def script_imports():
    """Every module the pipeline scripts import, minus the scripts themselves."""
    files = [os.path.join(d, f) for d in SCRIPT_DIRS for f in os.listdir(d) if f.endswith('.py')]
    local = {os.path.basename(f)[:-3] for f in files}
    found = set()
    for f in files:
        with open(f, encoding='utf-8') as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                found.add(node.module)
                # `from pkg import sub` may name a submodule
                found.update('%s.%s' % (node.module, a.name) for a in node.names)
    return sorted({module_name(m) for m in found if m.split('.')[0] not in local} - {None})


def package():
    os.makedirs(RELEASE, exist_ok=True)
    out = os.path.join(RELEASE, 'IPTV-Forge-windows.zip')
    subprocess.check_call(['git', '-C', ROOT, 'archive', '--format=zip',
                           '--prefix=IPTV-Forge/', '-o', out, 'HEAD'])
    with zipfile.ZipFile(out, 'a', zipfile.ZIP_DEFLATED) as z:
        z.write(EXE, 'IPTV-Forge/IPTV-Forge.exe')
    shutil.copy2(EXE, RELEASE)
    dirty = subprocess.run(['git', '-C', ROOT, 'status', '--porcelain'],
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        print('\nnote: uncommitted changes are NOT in the zip:\n' + dirty)
    print('\npacked %s  (%s)' % (RELEASE, ', '.join(sorted(os.listdir(RELEASE)))))


def main():
    work = tempfile.mkdtemp(prefix='iptv_forge_build_')
    hidden = script_imports()
    print('bundled for the scripts: %s\n' % ', '.join(hidden))
    args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed',
            '--name', 'IPTV-Forge', '--icon', os.path.join(HERE, 'ui', 'icon.ico'),
            '--add-data', os.path.join(HERE, 'ui') + os.pathsep + 'ui',
            '--distpath', ROOT, '--workpath', work, '--specpath', work,
            '--exclude-module', 'tkinter']
    for m in hidden:
        args += ['--hidden-import', m]
    rc = subprocess.call(args + [os.path.join(HERE, 'forge_gui.py')])
    shutil.rmtree(work, ignore_errors=True)
    if rc == 0:
        print('\nbuilt %s' % EXE)
        if '--zip' in sys.argv:
            package()
    sys.exit(rc)


if __name__ == '__main__':
    main()
