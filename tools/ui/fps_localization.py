"""Read and minimally patch the game's own FPS localization table.

The original resource already contains all 25 translations of the Unlimited
option. The UI must pass its $-prefixed localization key to QDText, whose native
translator handles language selection and the game's existing fonts.
Only the Spain-Spanish value is changed to the user's requested SIN LÍMITE;
Latin-American Spanish already contains that exact accented spelling.
"""
import csv
import hashlib
import json
import struct
from pathlib import Path

KEY = 'GUI_MENU_OPTIONS_VIDEO_FPSLIMIT_UNLIMITED'
UI_KEY = '$' + KEY
SPANISH_LABEL = 'SIN LÍMITE'
RESOURCE_ID = 2348
RESOURCE_TYPE = 1016
ORIGINAL_SHA256 = 'bd1c9e289bd105cac81659f248ec3d0518c297283560b030ed36198eaf32e1a9'
LANGUAGES = {
    'FRE': 'français', 'ENG': 'English', 'GER': 'Deutsch', 'ITA': 'italiano',
    'SPA': 'español (España)', 'DUT': 'Nederlands', 'POR': 'português (Portugal)',
    'SWE': 'svenska', 'DAN': 'dansk', 'NOR': 'norsk', 'FIN': 'suomi',
    'RUS': 'русский', 'POL': 'polski', 'JPN': '日本語', 'KOR': '한국어',
    'CHI': '繁體中文', 'GRE': 'ελληνικά', 'CZE': 'čeština', 'HUN': 'magyar',
    'CRO': 'hrvatski', 'MEX': 'español (Latinoamérica)', 'BRA': 'português (Brasil)',
    'TUR': 'Türkçe', 'ARA': 'العربية', 'SCH': '简体中文',
}

def sha(data):
    return hashlib.sha256(data).hexdigest()

class LocalizationResource:
    """Strict parser for this local resource's LOCALIZ_ version-6 structure."""
    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.languages = {}
        self.spans = {}
        self.flags = {}
        if self.take(8) != b'COM_CONT' or self.u32() != 6:
            raise ValueError('Unsupported COM_CONT header')
        size = self.u32()
        self.take(size)
        if self.take(8) != b'LOADCONT' or self.u32() != 2 or self.u32() != 0:
            raise ValueError('Unsupported LOADCONT header')
        if self.take(8) != b'LOCALIZ_' or self.u32() != 6:
            raise ValueError('Unsupported LOCALIZ_ header')
        self.size_offset = self.pos
        size = self.u32()
        end = self.pos + size
        if end != len(data):
            raise ValueError('Localization block length does not match its resource')
        count = self.u32()
        for _ in range(count):
            present = self.take(1)[0]
            if present != 1:
                raise ValueError('Absent language record is not supported')
            lang = self.sized('ascii')
            if lang in self.languages:
                raise ValueError('Duplicate language')
            entries, spans, flags = {}, {}, {}
            for _ in range(self.u32()):
                key = self.sized('ascii')
                if key in entries:
                    raise ValueError('Duplicate key')
                start = self.pos
                text = self.sized('utf-16-le')
                spans[key] = (start, self.pos)
                entries[key] = text
                flags[key] = self.u32()
            if self.u32() != 0:
                raise ValueError('Unexpected trailing language section')
            self.languages[lang], self.spans[lang], self.flags[lang] = entries, spans, flags
        if self.pos != end:
            raise ValueError('Unparsed localization data')

    def take(self, size):
        if size < 0 or self.pos + size > len(self.data):
            raise ValueError('Truncated localization data')
        value = self.data[self.pos:self.pos + size]
        self.pos += size
        return value

    def u32(self):
        return struct.unpack('<I', self.take(4))[0]

    def sized(self, encoding):
        return self.take(self.u32()).decode(encoding, errors='strict')

    def replace(self, replacements):
        edits = []
        for (lang, key), text in replacements.items():
            start, end = self.spans[lang][key]
            encoded = text.encode('utf-16-le', errors='strict')
            edits.append((start, end, struct.pack('<I', len(encoded)) + encoded))
        output = bytearray(self.data)
        for start, end, replacement in sorted(edits, reverse=True):
            output[start:end] = replacement
        struct.pack_into('<I', output, self.size_offset, len(output) - self.size_offset - 4)
        return bytes(output)

def original_resource():
    data = Path('analysis/localization/2348.bin').read_bytes()
    if sha(data) != ORIGINAL_SHA256:
        raise ValueError('Unexpected localization resource')
    return data

def build_localization(out):
    original = original_resource()
    parsed = LocalizationResource(original)
    if set(parsed.languages) != set(LANGUAGES):
        raise ValueError('Supported languages changed')
    if any(not entries.get(KEY, '').strip() for entries in parsed.languages.values()):
        raise ValueError('Unlimited is not translated in every language')
    if parsed.languages['SPA'][KEY] != 'ILIMITADOS' or parsed.languages['MEX'][KEY] != SPANISH_LABEL:
        raise ValueError('Unexpected Spanish source translations')
    modified = parsed.replace({('SPA', KEY): SPANISH_LABEL})
    verified = LocalizationResource(modified)
    changes = []
    for lang, entries in parsed.languages.items():
        for key, value in entries.items():
            if value != verified.languages[lang][key]:
                changes.append((lang, key, value, verified.languages[lang][key]))
    if changes != [('SPA', KEY, 'ILIMITADOS', SPANISH_LABEL)] or parsed.flags != verified.flags:
        raise ValueError('Unexpected translation modifications')
    out.mkdir(parents=True, exist_ok=True)
    path = out / f'{RESOURCE_ID}.bin'
    path.write_bytes(modified)
    translations = [{'code': lang, 'language': LANGUAGES[lang],
                     'text': entries[KEY], 'source': 'user_requested_spelling' if lang == 'SPA' else 'original_game_translation'}
                    for lang, entries in verified.languages.items()]
    report = {'localization_key': UI_KEY, 'language_count': len(translations),
              'translations': translations,
              'validation': {'all_25_languages_present': True, 'utf16_round_trip': True,
                             'only_spain_spanish_value_changed': True},
              'runtime_validation': 'Pending in-game language switching and font/layout checks.'}
    (out / 'localization.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    resource = {'type': RESOURCE_TYPE, 'id': RESOURCE_ID, 'name': 'LOCALIZ_ menu text',
                'path': str(path.resolve()), 'original_sha256': sha(original), 'modified_sha256': sha(modified),
                'original_size': len(original), 'modified_size': len(modified)}
    return resource, report

if __name__ == '__main__':
    resource, report = build_localization(Path('build/fps_menu'))
    print(json.dumps({'resource': resource, 'localization': report}, ensure_ascii=True, indent=2))
