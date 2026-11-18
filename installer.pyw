"""GUI launcher and isolated UI build worker for the standalone executable."""
import argparse
import sys

from i18n import LANGUAGES
from installer_gui import main
from patch_cli import main as console


if __name__ == '__main__':
    if sys.argv[1:2] == ['--build-ui']:
        raise SystemExit(console(sys.argv[1:]))
    elif sys.argv[1:2] == ['--cli']:
        raise SystemExit(console(sys.argv[2:]))
    else:
        cli = argparse.ArgumentParser()
        cli.add_argument('--lang',choices=LANGUAGES)
        cli.add_argument('--game-dir',default='')
        args = cli.parse_args()
        main(args.lang,args.game_dir)
