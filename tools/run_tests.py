"""Run the public test suite; generated UI tests use a prepared local copy."""
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
work = root/'.work'
env = dict(os.environ, PYTHONPATH=os.pathsep.join(map(str,(root,root/'tools/ui'))),
           PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
patterns = ['test_languages.py','test_installer*.py','test_winmm_proxy.py']
if (work/'build/screen_anchors/manifest.json').is_file():
    patterns.extend(('test_fps_localization.py','test_screen_anchors.py'))
else:
    print('UI asset tests require install.py prepare --game-dir PATH.',flush=True)
for pattern in patterns:
    subprocess.run([sys.executable,'-m','unittest','discover','-s',str(root/'tests'),
                    '-p',pattern,'-q'],cwd=work if work.is_dir() else root,env=env,check=True)
