"""Validate the actual built resources, without installing or launching the game.

Run from the workspace after `python build_fps_menu.py`:
    python -m unittest discover -s tests -p test_fps_localization.py -v
"""
import hashlib
import json
import struct
import unittest
from pathlib import Path

from fps_localization import KEY, UI_KEY, LANGUAGES, LocalizationResource
from inspect_abc import ABC, abc_blocks, opcode_table


class FpsLocalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = Path('build/fps_menu')
        cls.manifest = json.loads((cls.output / 'manifest.json').read_text())
        cls.original_loc = LocalizationResource(Path('analysis/localization/2348.bin').read_bytes())
        cls.modified_loc = LocalizationResource((cls.output / '2348.bin').read_bytes())
        original_block = next(abc_blocks(217))
        cls.original_abc = ABC(original_block['data'])
        cls.ops = opcode_table()
        # Parse the built SWF tag boundaries independently of the builder.
        raw = (cls.output / '217.bin').read_bytes()
        off = original_block['swf_offset']
        length = struct.unpack_from('<I', raw, off + 4)[0]
        assert struct.unpack_from('<I', raw, off - 4)[0] == length
        assert struct.unpack_from('<I', raw, 273)[0] == len(raw) - 277
        swf = raw[off:off + length]
        pos = 8 + (5 + 4 * (swf[8] >> 3) + 7) // 8 + 4
        blocks = []
        while pos + 2 <= len(swf):
            header = struct.unpack_from('<H', swf, pos)[0]
            pos += 2
            kind, size = header >> 6, header & 63
            if size == 63:
                size = struct.unpack_from('<I', swf, pos)[0]
                pos += 4
            assert pos + size <= len(swf)
            if kind == 82:
                begin = swf.index(0, pos + 4, pos + size) + 1
                blocks.append(swf[begin:pos + size])
            pos += size
            if kind == 0:
                break
        assert len(blocks) == 1
        cls.modified_abc = ABC(blocks[0])

    def test_every_official_language_resolves_a_nonempty_translation(self):
        self.assertEqual(set(self.modified_loc.languages), set(LANGUAGES))
        self.assertEqual(len(self.modified_loc.languages), 25)
        for language, entries in self.modified_loc.languages.items():
            with self.subTest(language=language):
                value = entries[KEY]
                self.assertTrue(value.strip())
                self.assertEqual(value, value.encode('utf-16-le').decode('utf-16-le'))
        self.assertEqual(self.modified_loc.languages['ENG'][KEY], 'UNLIMITED')
        self.assertEqual(self.modified_loc.languages['ARA'][KEY], 'غير محدود')
        self.assertEqual(self.modified_loc.languages['JPN'][KEY], '無制限')

    def test_both_spanish_variants_have_the_requested_accent(self):
        for language in ('SPA', 'MEX'):
            self.assertEqual(self.modified_loc.languages[language][KEY], 'SIN LÍMITE')
            self.assertIn(b'\xcd\x00', self.modified_loc.languages[language][KEY].encode('utf-16-le'))

    def test_only_requested_spain_spanish_value_changed(self):
        expected = {language: dict(entries) for language, entries in self.original_loc.languages.items()}
        expected['SPA'][KEY] = 'SIN LÍMITE'
        self.assertEqual(self.modified_loc.languages, expected)
        self.assertEqual(self.modified_loc.flags, self.original_loc.flags)
        start, end = self.original_loc.spans['SPA'][KEY]
        self.assertEqual(self.modified_loc.data[:start], self.original_loc.data[:start])
        self.assertEqual(self.modified_loc.data[end:], self.original_loc.data[end:])
        self.assertEqual(len(self.modified_loc.data), len(self.original_loc.data))

    def test_ui_uses_a_localization_key_and_keeps_native_choice_values(self):
        method = next(b for b in self.modified_abc.bodies if b['name'].endswith('MenuOptionsPageVideoPC::addBasicOptions'))
        instructions = self.modified_abc.disassemble(method, self.ops)
        choices = []
        for i, instruction in enumerate(instructions):
            if instruction['opcode'] != 0x2c:
                continue
            value = self.modified_abc.strings[instruction['args'][0]]
            if value in ('30', '60', '90', '144', UI_KEY):
                self.assertEqual(instructions[i+1]['opcode'], 0x24)  # Native enum argument.
                choices.append((value, instructions[i+1]['args'][0]))
        self.assertEqual(choices, [('30', 0), ('60', 1), ('90', 2), ('144', 3), (UI_KEY, 4)])
        self.assertNotIn('SIN LIMITE', self.modified_abc.strings)
        self.assertNotIn('SIN LÍMITE', self.modified_abc.strings)

    def test_localization_callback_repositions_fps_using_existing_layout(self):
        method = next(b for b in self.modified_abc.bodies if b['name'].endswith('MenuOptionsPageVideoPC::onLocalize'))
        tail = self.modified_abc.disassemble(method, self.ops)[-4:]
        self.assertEqual([i['instruction'] for i in tail], ['getlocal0', 'getproperty', 'callpropvoid', 'returnvoid'])
        self.assertTrue(tail[1]['note'].endswith('::_fps'))
        self.assertEqual(tail[2]['note'], 'repositionChoices')
        self.assertEqual(tail[2]['args'][1], 0)

    def test_preserves_native_font_and_language_dispatch_methods(self):
        original = {b['method']: b for b in self.original_abc.bodies}
        changed = []
        for body in self.modified_abc.bodies:
            self.modified_abc.disassemble(body, self.ops)
            if original[body['method']]['code'] != body['code']:
                changed.append(body['name'].split('::')[-1])
        self.assertCountEqual(changed, ['addBasicOptions', 'onLocalize'])
        expected = list(self.original_abc.strings)
        expected[expected.index('Unlimited')] = UI_KEY
        self.assertEqual(self.modified_abc.strings, expected)

    def test_install_manifest_hashes_match_all_built_resources(self):
        self.assertEqual({(r['type'], r['id']) for r in self.manifest['resources']}, {(18002, 217), (1016, 2348)})
        for resource in self.manifest['resources']:
            data = Path(resource['path']).read_bytes()
            self.assertEqual(len(data), resource['modified_size'])
            self.assertEqual(hashlib.sha256(data).hexdigest(), resource['modified_sha256'])


if __name__ == '__main__':
    unittest.main()
