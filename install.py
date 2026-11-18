"""Installer for Detroit Adaptive Display. Python 3.10+ on 64-bit Windows."""
import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

from i18n import catalog, default_language, LANGUAGES

ROOT = Path(__file__).resolve().parent
RELEASE = json.loads((ROOT / 'release.json').read_text(encoding='utf-8'))
EXE = 'DetroitBecomeHuman.exe'
INDEX, PACK, DLL = 'BigFile_PC.idx', 'BigFile_PC.d29', 'winmm.dll'
BACKUP = 'DetroitAdaptiveDisplay.backup'
RECORD = struct.Struct('>7I')
sys.path.insert(0, str(ROOT/'tools/ui'))
import portable_layout


class InstallError(ValueError):
    def __init__(self, key, detail=None):
        self.key = key
        self.detail = str(detail) if detail is not None else ""
        super().__init__(key, self.detail)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def stream_hash(stream):
    result = hashlib.sha256()
    for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
        result.update(chunk)
    return result.hexdigest()


def file_hash(path):
    if not path.exists():
        return None
    with path.open('rb') as stream:
        return stream_hash(stream)


def game_folder(location):
    if not str(location).strip():
        raise InstallError('hint')
    folder = Path(location).resolve()
    if folder.name.lower() == EXE.lower() and folder.is_file():
        folder = folder.parent
    if folder.is_dir():
        for candidate in (folder, *folder.parents):
            if (candidate/EXE).is_file():
                return candidate
    raise InstallError('hint')


def native_engine(stream):
    """Select the full profile only for the engine the bundled DLL implements."""
    if stream_hash(stream) == RELEASE['exe_sha256']:
        return True
    # A new checksum, COFF timestamp or trailing certificate does not move
    # the engine. All other header, section and data bytes must match.
    profile = RELEASE['engine_image']
    size = stream.tell()
    stream.seek(0)
    if size >= profile['size']:
        first = bytearray(stream.read(4096))
        entry = profile['certificate']
        certificate = struct.unpack_from('<II', first, entry)
        trailing = size - profile['size']
        if certificate == ((profile['size'], trailing) if trailing else (0, 0)):
            for field, length in [('timestamp', 4), ('checksum', 4), ('certificate', 8)]:
                pos = profile[field]
                first[pos:pos+length] = bytes(length)
            result = hashlib.sha256(first)
            left = profile['size'] - len(first)
            while left:
                chunk = stream.read(min(left, 4 * 1024 * 1024))
                if not chunk:
                    raise InstallError('changed', EXE)
                result.update(chunk)
                left -= len(chunk)
            if result.hexdigest() == profile['sha256']:
                return True
        stream.seek(0)
    header = stream.read(64)
    if len(header) == 64 and header[:2] == b'MZ':
        offset = int.from_bytes(header[60:64], 'little')
        stream.seek(offset)
        pe = stream.read(26)
        if (offset >= 64 and len(pe) == 26 and pe[:6] == b'PE\0\0\x64\x86'
                and pe[24:26] == b'\x0b\x02' and int.from_bytes(pe[22:24], 'little') & 0x2002 == 2):
            return False
    raise InstallError('incompatible')


@contextmanager
def game_guard(game):
    # Windows denies this exclusive writable handle for a running mapped image.
    # Holding it serializes installers and prevents a launch during commit.
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    open_file = kernel.CreateFileW
    open_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                          wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    open_file.restype = wintypes.HANDLE
    handle = open_file(str(game/EXE), 0xc0000000, 0, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        error = ctypes.get_last_error()
        raise InstallError('busy', error)
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(wintypes.HANDLE(handle))
        raise
    with os.fdopen(fd, 'rb') as stream:
        yield native_engine(stream)


def resource_data(game, fields):
    offset, size, alt, package = fields[3:]
    if alt or package > 99 or not 0 < size <= 16 * 1024 * 1024:
        return None
    filename = f'BigFile_PC.d{package:02}' if package else 'BigFile_PC.dat'
    try:
        with (game/filename).open('rb') as source:
            source.seek(offset)
            data = source.read(size)
    except FileNotFoundError:
        return None
    return data if len(data) == size else None


def read_resources(game, index, *, available=False):
    if not index.startswith(b'QUANTICDREAMTABINDEX') or len(index) < 105:
        raise InstallError('archives')
    count, = struct.unpack_from('>I', index, 101)
    if len(index) != 105 + count * RECORD.size:
        raise InstallError('archives')
    wanted = {(r['type'], r['id']): r for r in RELEASE['resources']}
    found = {}
    for pos in range(105, len(index), RECORD.size):
        fields = RECORD.unpack_from(index, pos)
        typ, _, ident = fields[:3]
        resource = wanted.get((typ, ident))
        if resource is None:
            continue
        if ident in found:
            raise InstallError('archives', ident)
        data = resource_data(game, fields)
        if data is None:
            if available:
                continue
            raise InstallError('archives', ident)
        found[ident] = (pos, data)
    if not available and len(found) != len(wanted):
        raise InstallError('archives')
    return found


def match_resources(resources, key):
    return all(r['id'] in resources and digest(resources[r['id']][1]) == r[key] for r in RELEASE['resources'])


def layout_candidates(game, index, resources):
    recipes = {r['layout_program']['original']:r for r in RELEASE['resources'] if 'layout_program' in r}
    candidates = {}
    seen = set()
    def identify(pos, data):
        recipe = recipes.get(portable_layout.signature(data))
        if recipe:
            candidates[pos] = (recipe, data)
            seen.add(recipe['id'])
    for pos, data in resources.values():
        identify(pos, data)
    if len(seen) != len(recipes):
        # Some editions move an interface to a different entry or archive.
        checked = {pos for pos,_ in resources.values()}
        for pos in range(105, len(index), RECORD.size):
            fields = RECORD.unpack_from(index, pos)
            if fields[0] == 18002 and pos not in checked:
                data = resource_data(game, fields)
                if data:
                    identify(pos, data)
    return candidates


def folder_state(game):
    with (game/EXE).open('rb') as exe:
        return inspect_data(game, native_engine(exe))


def inspect_data(game, native):
    if (game/BACKUP).exists():
        journal = load_journal(game)
        check_files(game, journal)
        if all(file_hash(game/name) == sha for name, sha in journal['new'].items()):
            if DLL not in journal['new']:
                return 'installed_ui'
            if native and journal['new'][DLL] in (RELEASE['dll_sha256'], RELEASE['legacy_dll_sha256']):
                return 'installed'
        return 'recovery'
    if not (game/INDEX).is_file():
        raise InstallError('archives', INDEX)
    index = (game/INDEX).read_bytes()
    resources = read_resources(game, index, available=True)
    if native:
        if file_hash(ROOT/'bin'/DLL) != RELEASE['dll_sha256']:
            raise InstallError('corrupt')
        existing = file_hash(game/DLL)
        if existing in (RELEASE['dll_sha256'], RELEASE['legacy_dll_sha256']) and match_resources(resources, 'modified_sha256'):
            return 'unmanaged'
        if (game/PACK).is_file() and match_resources(resources, 'original_sha256'):
            if existing is not None:
                raise InstallError('foreign')
            return 'ready'
    if layout_candidates(game, index, resources):
        return 'ready_ui'
    raise InstallError('no_layout')


def build_resources(resources, work):
    for directory in ('analysis/ui', 'analysis/localization', 'build/native'):
        (work/directory).mkdir(parents=True, exist_ok=True)
    movies = []
    for r in RELEASE['resources']:
        data = resources[r['id']][1]
        if digest(data) != r['original_sha256']:
            raise InstallError('archives', r['id'])
        directory = 'analysis/localization' if 'movie' not in r else 'analysis/ui'
        (work/directory/f"{r['id']}.bin").write_bytes(data)
        if 'movie' in r:
            movies.append(r['movie'])
    (work/'analysis/ui_signatures.json').write_text(json.dumps(movies), encoding='utf-8')
    native = work/'build/native'
    shutil.copyfile(ROOT/'bin'/DLL, native/DLL)
    (native/'manifest.json').write_text(json.dumps(dict(version=RELEASE['build'], sha256=RELEASE['dll_sha256'])))
    for script in ('build_fps_menu.py', 'build_screen_anchors.py'):
        command = ([sys.executable, '--build-ui', script] if getattr(sys, 'frozen', False) else
                   [sys.executable, '-B', '-X', 'utf8', str(ROOT/'tools/ui'/script)])
        task = subprocess.run(command,
                              cwd=work, capture_output=True)
        if task.returncode:
            raise InstallError('corrupt', script)
    built = {}
    for r in RELEASE['resources']:
        group = 'fps_menu' if 'movie' not in r else 'screen_anchors'
        data = (work/'build'/group/f"{r['id']}.bin").read_bytes()
        if digest(data) != r['modified_sha256']:
            raise InstallError('corrupt', r['id'])
        built[r['id']] = data
    return built


def load_journal(game):
    backup = game/BACKUP
    state = json.loads((backup/'journal.json').read_text(encoding='utf-8'))
    # Older full installations have no "pack" field and always use d29.
    pack = state.get('pack', PACK)
    if pack not in {'BigFile_PC.dat', *(f'BigFile_PC.d{i:02}' for i in range(1, 100))}:
        raise InstallError('backup_error')
    names = {INDEX, pack}
    if 'pack' not in state:
        names.add(DLL)
    if (state.get('release') not in ('0.8.3', RELEASE['version']) or set(state['old']) != names
            or set(state['new']) != names or state['old'].get(DLL) is not None):
        raise InstallError('backup_error')
    for name in (INDEX, pack):
        if file_hash(backup/name) != state['old'][name]:
            raise InstallError('backup_error', name)
    return state


def check_files(game, state):
    for name in state['old']:
        if file_hash(game/name) not in (state['old'][name], state['new'][name]):
            raise InstallError('changed', name)


def restore(game):
    backup = game/BACKUP
    state = load_journal(game)
    check_files(game, state)
    originals = (INDEX, state.get('pack', PACK))
    if {f.name for f in backup.iterdir()} != {*originals, 'journal.json'}:
        raise InstallError('backup_error', BACKUP)
    with tempfile.TemporaryDirectory(dir=game, prefix='.dad-restore-') as tmp:
        for name in originals:
            if file_hash(game/name) != state['old'][name]:
                copy = Path(tmp)/name
                shutil.copyfile(backup/name, copy)
                if file_hash(copy) != state['old'][name]:
                    raise InstallError('backup_error', name)
                os.replace(copy, game/name)
        if DLL in state['old'] and (game/DLL).exists():
            (game/DLL).unlink()
        if any(file_hash(game/n) != sha for n,sha in state['old'].items()):
            raise InstallError('backup_error')
        # Retire the journal atomically before clearing its files, so an
        # interrupted cleanup cannot leave an invalid active journal.
        retired = Path(tmp)/'restored'
        backup.rename(retired)


def destination_pack(game, index, built):
    required = sum(len(data) + 2047 for data in built.values())
    packages = {fields[-1] for fields in RECORD.iter_unpack(memoryview(index)[105:]) if fields[-1] <= 99}
    for number in sorted(packages, reverse=True):
        name = f'BigFile_PC.d{number:02}' if number else 'BigFile_PC.dat'
        path = game/name
        if path.is_file() and path.stat().st_size + required < 0x80000000:
            return name, number
    raise InstallError('archives')


def install(game, notify, ui_only=False):
    index = (game/INDEX).read_bytes()
    original = read_resources(game, index, available=ui_only)
    if (not ui_only and (game/DLL).exists()) or (game/BACKUP).exists():
        raise InstallError('recovery')
    if ui_only:
        notify('checking')
        candidates = layout_candidates(game, index, original)
        if not candidates:
            raise InstallError('archives')
        built = {pos:portable_layout.apply(recipe['id'], data, recipe['layout_program'])
                 for pos,(recipe,data) in candidates.items()}
        pack_name, package = destination_pack(game, index, built)
    else:
        with tempfile.TemporaryDirectory(prefix='detroit-ui-') as work:
            notify('generating')
            built = {original[i][0]: data for i,data in build_resources(original, Path(work)).items()}
        pack_name, package = PACK, 29
    with tempfile.TemporaryDirectory(dir=game, prefix='.dad-install-') as temp:
        stage = Path(temp)
        backup = stage/'original'
        backup.mkdir()
        (backup/INDEX).write_bytes(index)
        shutil.copyfile(game/pack_name, backup/pack_name)
        notify('backup')
        shutil.copyfile(backup/pack_name, stage/pack_name)
        new_index = bytearray(index)
        with (stage/pack_name).open('ab') as pack:
            for pos, data in built.items():
                offset = (pack.tell()+2047) & ~2047
                if offset + len(data) >= 0x80000000:
                    raise InstallError('archives')
                pack.write(bytes(offset-pack.tell()))
                pack.write(data)
                fields = RECORD.unpack_from(index, pos)
                RECORD.pack_into(new_index, pos, *fields[:3], offset, len(data), 0, package)
            pack.flush()
            os.fsync(pack.fileno())
        (stage/INDEX).write_bytes(new_index)
        old = {INDEX: digest(index), pack_name: file_hash(backup/pack_name)}
        # Write data before publishing index entries which reference that data.
        commit = [pack_name, INDEX]
        if not ui_only:
            shutil.copyfile(ROOT/'bin'/DLL, stage/DLL)
            old[DLL] = None
            commit.append(DLL)
        new = {n: file_hash(stage/n) for n in commit}
        state = dict(release=RELEASE['version'], old=old, new=new)
        if ui_only:
            state.update(pack=pack_name, resources=[RECORD.unpack_from(index, pos)[2] for pos in built])
        (backup/'journal.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
        if any(file_hash(game/n) != old[n] for n in old) or (not ui_only and new[DLL] != RELEASE['dll_sha256']):
            raise InstallError('changed')
        backup.rename(game/BACKUP)
        try:
            notify('applying')
            for n in commit:
                os.replace(stage/n, game/n)
            result = (game/INDEX).read_bytes()
            if any(resource_data(game, RECORD.unpack_from(result, pos)) != data for pos,data in built.items()):
                raise InstallError('corrupt')
            if any(file_hash(game/n) != new[n] for n in new):
                raise InstallError('corrupt')
        except BaseException:
            restore(game)
            raise


def run(action, game, notify=print, *, expected=None):
    game = game_folder(game)
    if action == 'verify':
        return folder_state(game)
    if action == 'prepare':
        if folder_state(game) != 'ready':
            raise InstallError('archives')
        build_resources(read_resources(game, (game/INDEX).read_bytes()), ROOT/'.work')
        return 'prepared'
    with game_guard(game) as native:
        if action == 'restore' and (game/BACKUP).is_dir():
            restore(game)
            return 'restored'
        state = inspect_data(game, native)
        if action == 'install' and state in ('ready', 'ready_ui'):
            if expected is not None and expected != state:
                return state
            install(game, notify, ui_only=state == 'ready_ui')
            return 'installed' if state == 'ready' else 'installed_ui'
        return state


def error_text(error):
    if isinstance(error, InstallError):
        return error.key, error.detail
    if isinstance(error, (KeyError, json.JSONDecodeError)):
        return 'backup_error', ''
    return 'io', str(getattr(error, 'winerror', '') or '')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('verify', 'install', 'restore', 'prepare'))
    parser.add_argument('--game-dir', type=Path, required=True)
    parser.add_argument('--lang', choices=LANGUAGES, default=default_language())
    args = parser.parse_args()
    t = catalog(args.lang)
    try:
        print(t[run(args.action, args.game_dir, lambda key: print(t[key]))])
    except (OSError, ValueError, KeyError) as error:
        key, detail = error_text(error)
        parser.exit(1, (t[key] + ' ' + detail).strip()+'\n')
