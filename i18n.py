"""Language selection shared by the Windows installer and its command line."""
import ctypes
from functools import lru_cache
import json
from pathlib import Path
import re

DIRECTORY = Path(__file__).resolve().parent / 'locales'
LANGUAGES = tuple(p.stem for p in sorted(DIRECTORY.glob('*.json')))


@lru_cache(maxsize=None)
def catalog(code):
    if code not in LANGUAGES:
        raise ValueError(code)
    entries = json.loads((DIRECTORY/f'{code}.json').read_text(encoding='utf-8'))
    if code == 'ar':
        # An RTL paragraph can contain LTR product names, paths and extensions.
        # Give the Windows text renderer a base direction for mixed labels.
        for key, value in entries.items():
            if re.search('[A-Za-z]', value):
                tokens = re.sub(r'\.?[A-Za-z][A-Za-z0-9.]*[A-Za-z0-9]|[A-Za-z]',
                                lambda m: '\u202a'+m.group()+'\u202c', value)
                entries[key] = '\u202b'+tokens+'\u202c'
    return entries


def match_language(tag):
    parts = tag.replace('_', '-').lower().split('-')
    for code in LANGUAGES:
        if code.lower() == '-'.join(parts):
            return code
    language = parts[0]
    if language == 'zh':
        return 'zh-Hant' if set(parts) & {'hant', 'tw', 'hk', 'mo'} else 'zh-Hans'
    if language == 'es':
        return 'es-ES' if 'es' in parts[1:] else 'es-419'
    if language == 'pt':
        return 'pt-BR' if 'br' in parts else 'pt-PT'
    if language in ('no', 'nn'):
        return 'nb'
    return language if language in LANGUAGES else 'en'


def default_language():
    buf = ctypes.create_unicode_buffer(85)
    if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, len(buf)):
        return match_language(buf.value)
    return 'en'
