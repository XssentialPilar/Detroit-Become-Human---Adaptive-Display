from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from i18n import catalog, LANGUAGES
from installer_gui import Installer


class FolderSelectionTests(unittest.TestCase):
    def setUp(self):
        self.app = Mock(spec=Installer)
        self.app.window = Mock()
        self.app.folder = Mock()
        self.app.t = catalog('es-419')

    def test_confirm_updates_path_before_verifying(self):
        with tempfile.TemporaryDirectory() as directory:
            selected = Path(directory) / 'Selección 日本語'
            selected.mkdir()
            self.app.folder.get.return_value = directory
            with patch('installer_gui.filedialog.askdirectory', return_value=selected.as_posix()) as dialog:
                Installer.choose_folder(self.app)
            dialog.assert_called_once_with(parent=self.app.window, title=self.app.t['folder'],
                                           initialdir=directory, mustexist=True)
            self.app.folder.set.assert_called_once_with(str(selected))
            self.app.start.assert_called_once_with('verify')
            self.assertEqual([call[0] for call in self.app.method_calls][-2:], ['folder.set', 'start'])

    def test_cancel_preserves_entry_and_skips_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            for code in LANGUAGES:
                self.app.t = catalog(code)
                for current in ('', str(Path(directory) / 'missing')):
                    with self.subTest(code=code, current=current):
                        self.app.folder.get.return_value = current
                        with patch('installer_gui.filedialog.askdirectory', return_value='') as dialog:
                            Installer.choose_folder(self.app)
                        dialog.assert_called_once_with(parent=self.app.window, title=self.app.t['folder'],
                                                       mustexist=True)
                        self.app.folder.set.assert_not_called()
                        self.app.start.assert_not_called()
