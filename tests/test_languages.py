import ast
import itertools
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from i18n import catalog, LANGUAGES, match_language


class Languages(unittest.TestCase):
    def test_complete_catalogs(self):
        supported = 'ar cs da de el en es-419 es-ES fi fr hr hu it ja ko nb nl pl pt-BR pt-PT ru sv tr zh-Hans zh-Hant'.split()
        self.assertEqual(set(LANGUAGES), set(supported))
        english = catalog('en')
        required = set(english)
        self.assertEqual(len({catalog(code)['name'] for code in supported}),25)
        for code in supported:
            t = catalog(code)
            self.assertEqual(set(t),required,code)
            self.assertTrue(all(isinstance(value,str) and value.strip() and '\ufffd' not in value for value in t.values()))
            self.assertIn('DetroitBecomeHuman.exe',t['hint'])
            self.assertIn('winmm.dll',t['foreign'])
            if code != 'en':
                for key in ('ready','installed','busy','foreign','recovery','backup_error','hint'):
                    self.assertNotEqual(t[key],english[key],(code,key))
        self.assertEqual(catalog('es-419')['name'],'Español (Latinoamérica)')

    def test_installation_and_error_keys(self):
        tree = ast.parse((ROOT/'install.py').read_text(encoding='utf-8'))
        calls = (x for x in ast.walk(tree) if isinstance(x,ast.Call) and isinstance(x.func,ast.Name))
        keys = {c.args[0].value for c in calls if c.func.id in ('notify','InstallError') and c.args
                and isinstance(c.args[0],ast.Constant)}
        keys.update(('ready','installed','restored','unmanaged','recovery','io','prepared'))
        for code,key in itertools.product(LANGUAGES,keys):
            self.assertIn(key,catalog(code))

    def test_windows_locale_routing(self):
        for tag,expected in {'es-DO':'es-419','es-MX':'es-419','es_ES':'es-ES','pt_BR':'pt-BR',
                             'pt-PT':'pt-PT','zh-TW':'zh-Hant','zh-HK':'zh-Hant','zh-CN':'zh-Hans',
                             'ar-SA':'ar','ja-JP':'ja','nb-NO':'nb','xx-XX':'en'}.items():
            self.assertEqual(match_language(tag),expected)
