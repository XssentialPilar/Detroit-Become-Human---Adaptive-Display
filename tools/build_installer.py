"""Build the self-contained Windows installer with the checked-in language catalogs."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--distpath', str(root/'dist'),
           '--workpath', str(root/'build/installer'), '--specpath', str(root/'build')]
for pattern, dest in [('release.json','.'),('bin/winmm.dll','bin'),('locales/*.json','locales'),
                      ('tools/ui/*.py','tools/ui'),('tools/ui/reference/*','tools/ui/reference')]:
    command.extend(('--add-data',str(root/pattern)+';'+dest))
command.extend(('--hidden-import','csv'))
setup_icon = root/'assets/setup.ico'
portable_icon = root/'assets/portable.ico'
subprocess.run([*command, '--windowed', '--name', 'DetroitAdaptiveDisplay-Setup',
                '--icon', str(setup_icon), '--add-data', str(setup_icon)+';assets',
                str(root/'installer.pyw')], cwd=root, check=True)
subprocess.run([*command, '--console', '--name', 'DetroitAdaptiveDisplay-Patch',
                '--icon', str(portable_icon), str(root/'patch_cli.py')], cwd=root, check=True)
