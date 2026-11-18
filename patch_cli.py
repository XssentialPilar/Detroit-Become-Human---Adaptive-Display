"""Entry point for the portable patch and the installer's build workers."""
import argparse
import ctypes
from pathlib import Path
import runpy
import sys

from i18n import LANGUAGES, catalog, default_language
from install import error_text, game_folder, run


def main(arguments, *, double_click=False):
    if arguments[:1] == ['--build-ui']:
        if len(arguments) != 2 or arguments[1] not in ('build_fps_menu.py', 'build_screen_anchors.py'):
            return 2
        source = Path(__file__).resolve().parent/'tools/ui'
        sys.path.insert(0, str(source))
        runpy.run_path(str(source/arguments[1]), run_name='__main__')
        return 0

    if double_click:
        launcher = Path(sys.executable if getattr(sys, 'frozen', False) else __file__)
        arguments = ['install', '--game-dir', str(launcher.resolve().parent)]

    parser = argparse.ArgumentParser(description='Detroit Adaptive Display')
    parser.add_argument('action', choices=('verify', 'install', 'restore'))
    parser.add_argument('--game-dir', type=Path, default=Path.cwd())
    parser.add_argument('--lang', choices=LANGUAGES, default=default_language())
    args = parser.parse_args(arguments)
    messages = catalog(args.lang)
    def show(text):
        if sys.stdout is not None:
            print(text, flush=True)

    def finish(message, code):
        show(message)
        if double_click and sys.stdout is not None and sys.stdout.isatty():
            icon = 0x40 if code == 0 else 0x30
            ctypes.windll.user32.MessageBoxW(None, message, 'Detroit Adaptive Display', icon)
        return code

    try:
        game = game_folder(args.game_dir)
        show(str(game))
        expected = None
        if args.action == 'install':
            expected = run('verify', game)
            show(messages[expected])
        result = run(args.action, game, lambda key: show(messages[key]), expected=expected)
    except (OSError, ValueError, KeyError) as exc:
        key, detail = error_text(exc)
        if double_click and key == 'hint':
            key = 'portable_location'
        return finish((messages[key] + ' ' + detail).strip(), 1)
    valid = {'verify': ('ready', 'ready_ui', 'installed', 'installed_ui', 'unmanaged'),
             'install': ('installed', 'installed_ui', 'unmanaged'),
             'restore': ('ready', 'ready_ui', 'restored')}
    return finish(messages[result], 0 if result in valid[args.action] else 1)


if __name__ == '__main__':
    arguments = sys.argv[1:]
    raise SystemExit(main(arguments, double_click=not arguments))
