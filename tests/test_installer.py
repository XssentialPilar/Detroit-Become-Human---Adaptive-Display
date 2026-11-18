import os
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install as mod


class InstallerTest(unittest.TestCase):
    def setUp(self):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        self.game = Path(tempdir.name).resolve()
        self.before = b'original resource'
        self.after = b'adaptive resource'
        (self.game/mod.EXE).write_bytes(b'fixture')
        self.index = bytearray(105)
        self.index[:20] = b'QUANTICDREAMTABINDEX'
        struct.pack_into('>I', self.index, 101, 1)
        self.index.extend(mod.RECORD.pack(18002, 1, 63, 0, len(self.before), 0, 0))
        (self.game/mod.INDEX).write_bytes(self.index)
        (self.game/'BigFile_PC.dat').write_bytes(self.before)
        (self.game/mod.PACK).write_bytes(b'original pack')
        (self.game/'dinput8.dll').write_bytes(b'another mod')
        manifest = dict(mod.RELEASE, exe_sha256=mod.digest(b'fixture'), resources=[
            dict(type=18002,id=63,original_sha256=mod.digest(self.before),
                 modified_sha256=mod.digest(self.after))])
        for p in (patch.object(mod, 'RELEASE', manifest),
                  patch.object(mod, 'build_resources', return_value={63:self.after})):
            p.start()
            self.addCleanup(p.stop)

    def action(self, action):
        return mod.run(action, self.game, lambda _: None)

    def test_roundtrip_retry_and_unrelated_files(self):
        self.assertEqual(self.action('install'), 'installed')
        self.assertEqual(self.action('install'), 'installed')
        self.assertEqual(self.action('verify'), 'installed')
        self.assertEqual(self.action('restore'), 'restored')
        self.assertEqual((self.game/mod.INDEX).read_bytes(), self.index)
        self.assertEqual((self.game/mod.PACK).read_bytes(), b'original pack')
        self.assertEqual((self.game/'dinput8.dll').read_bytes(), b'another mod')
        self.assertFalse((self.game/mod.DLL).exists())
        self.assertFalse((self.game/mod.BACKUP).exists())

    def test_foreign_dll(self):
        (self.game/mod.DLL).write_bytes(b'foreign')
        with self.assertRaises(ValueError):
            self.action('install')
        self.assertEqual((self.game/mod.DLL).read_bytes(), b'foreign')
        self.assertEqual((self.game/mod.INDEX).read_bytes(), self.index)

    def test_incompatible_executable(self):
        (self.game/mod.EXE).write_bytes(b'update')
        with self.assertRaises(ValueError):
            self.action('install')
        self.assertFalse((self.game/mod.BACKUP).exists())

    def test_shader_cache_and_executable_paths(self):
        cache = self.game/'ShaderCache'/'nested'
        cache.mkdir(parents=True)
        for location in (self.game, self.game/mod.EXE, cache):
            self.assertEqual(mod.game_folder(location), self.game)
            self.assertEqual(mod.run('verify', location), 'ready')
        self.assertEqual(mod.run('install', cache), 'installed')
        self.assertEqual(mod.run('restore', cache), 'restored')
        self.assertFalse((cache/mod.BACKUP).exists())
        with self.assertRaises(mod.InstallError) as error:
            mod.run('verify', self.game/'typo')
        self.assertEqual(error.exception.key, 'hint')

    def test_old_full_backup_can_still_be_restored(self):
        self.action('install')
        journal = self.game/mod.BACKUP/'journal.json'
        state = json.loads(journal.read_bytes())
        state['release'] = '0.8.3'
        journal.write_text(json.dumps(state), encoding='utf8')
        self.assertEqual(self.action('restore'), 'restored')
        self.assertEqual((self.game/mod.INDEX).read_bytes(), self.index)

    def test_modified_resource(self):
        (self.game/'BigFile_PC.dat').write_bytes(b'x'*len(self.before))
        with self.assertRaises(ValueError):
            self.action('install')
        self.assertFalse((self.game/mod.DLL).exists())

    def test_changed_after_install(self):
        self.action('install')
        (self.game/mod.PACK).write_bytes(b'another change')
        with self.assertRaises(ValueError):
            self.action('restore')
        self.assertEqual((self.game/mod.PACK).read_bytes(), b'another change')
        self.assertTrue((self.game/mod.BACKUP).is_dir())

    def test_interrupted_commit_restores_both_originals(self):
        replace = os.replace
        def fail_index(source, target):
            if target == self.game/mod.INDEX and Path(source).parent.name.startswith('.dad-install-'):
                raise PermissionError('Simulated index lock')
            replace(source, target)
        with patch('os.replace', side_effect=fail_index), self.assertRaises(PermissionError):
            self.action('install')
        self.assertEqual(self.action('verify'), 'ready')
        self.assertEqual((self.game/mod.PACK).read_bytes(), b'original pack')

    def test_exclusive_executable(self):
        with mod.game_guard(self.game), self.assertRaises(ValueError):
            self.action('install')
        self.assertFalse((self.game/mod.BACKUP).exists())
