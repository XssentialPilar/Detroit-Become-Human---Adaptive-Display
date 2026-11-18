from io import BytesIO
from pathlib import Path
import hashlib
import json
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import install
import portable_layout


class LayoutCompatibilityTests(unittest.TestCase):
    def test_malformed_movie_is_not_a_candidate(self):
        for data in (b'', b'GFX', b'MENU_RES', b'MENU_RES' + bytes(80)):
            self.assertIsNone(portable_layout.signature(data))

    def test_engine_metadata_does_not_select_another_engine(self):
        image = bytearray(8192)
        image[:2] = b'MZ'
        struct.pack_into('<I', image, 60, 176)
        image[176:182] = b'PE\0\0\x64\x86'
        struct.pack_into('<HHH', image, 196, 240, 2, 0x20b)
        profile = dict(size=len(image), timestamp=184, checksum=264, certificate=344,
                       sha256=hashlib.sha256(image).hexdigest())
        with patch.dict(install.RELEASE, engine_image=profile):
            image[184] = 7
            image[264] = 9
            self.assertTrue(install.native_engine(BytesIO(image)))
            struct.pack_into('<II', image, 344, len(image), 8)
            image.extend(struct.pack('<IHH', 8, 0x200, 2))
            self.assertTrue(install.native_engine(BytesIO(image)))
            image[4100] ^= 1
            self.assertFalse(install.native_engine(BytesIO(image)))

    @unittest.skipUnless((ROOT/'.work/analysis/ui/111.bin').is_file(), 'requires prepared game resources')
    def test_other_engine_moved_resource_and_foreign_dll(self):
        source = (ROOT/'.work/analysis/ui/111.bin').read_bytes()
        # Preserve an edition-specific change outside the embedded GFx program.
        source = source[:-1] + bytes([source[-1] ^ 1])
        with tempfile.TemporaryDirectory() as tmp:
            game = Path(tmp)
            (game/install.EXE).write_bytes(Path(sys.executable).read_bytes())
            (game/install.DLL).write_bytes(b'unrelated DLL')
            (game/'ShaderCache').mkdir()
            index = bytearray(105)
            index[:20] = b'QUANTICDREAMTABINDEX'
            struct.pack_into('>I', index, 101, 2)
            index.extend(install.RECORD.pack(18002, 1, 811, 0, len(source), 0, 3))
            index.extend(install.RECORD.pack(18002, 1, 64, len(source), 13, 0, 3))
            original = source + b'other program'
            pack = game/'BigFile_PC.d03'
            (game/install.INDEX).write_bytes(index)
            pack.write_bytes(original)
            def run(action, **kwargs):
                return install.run(action, game/'ShaderCache', lambda _: None, **kwargs)
            self.assertEqual(run('verify'), 'ready_ui')
            self.assertEqual(run('install', expected='ready'), 'ready_ui')
            self.assertFalse((game/install.BACKUP).exists())
            self.assertEqual(run('install'), 'installed_ui')
            self.assertEqual(run('verify'), 'installed_ui')
            self.assertEqual(run('install'), 'installed_ui')
            journal = json.loads((game/install.BACKUP/'journal.json').read_bytes())
            self.assertEqual(journal['resources'], [811])
            self.assertNotIn(install.DLL, journal['new'])
            patched_index = (game/install.INDEX).read_bytes()
            self.assertEqual(patched_index[105 + install.RECORD.size:], index[105 + install.RECORD.size:])
            fields = install.RECORD.unpack_from(patched_index, 105)
            self.assertEqual(install.resource_data(game, fields)[-1], source[-1])
            self.assertEqual(run('restore'), 'restored')
            self.assertEqual(pack.read_bytes(), original)
            self.assertEqual((game/install.INDEX).read_bytes(), index)
            self.assertEqual((game/install.DLL).read_bytes(), b'unrelated DLL')
            pack.write_bytes(bytes(len(original)))
            with self.assertRaises(install.InstallError) as error:
                run('install')
            self.assertEqual(error.exception.key, 'no_layout')
            self.assertFalse((game/install.BACKUP).exists())
