"""Build the installer distribution, its private resource DLL, and the portable ZIP."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile

root = Path(__file__).resolve().parents[1]
version = json.loads((root/'release.json').read_text(encoding='utf-8'))['version']
prefix = f'DetroitAdaptiveDisplay-{version}'
dist = root/'dist'
dist.mkdir(exist_ok=True)
exe = 'DetroitAdaptiveDisplay-Setup.exe'
dll = 'DetroitAdaptiveDisplay.SetupData.dll'

required = ['.gitignore','README.md','README-RELEASE.md','CMakeLists.txt','requirements-dev.txt','release.json',
            'installer.pyw','installer_gui.py','i18n.py','install.py','patch_cli.py',
            'generate_native_loader.py','build_native_loader.py','bin/winmm.dll']
sources = {name:root/name for name in required}
for directory, extensions in {'assets':{'.ico'},'locales':{'.json'},'src':{'.cpp','.hpp','.S'},
                              'include':{'.hpp'},'tests':{'.py','.cpp'},
                              'tools':{'.py','.tbl','.txt'},'docs':{'.md','.png'}}.items():
    for path in sorted((root/directory).rglob('*')):
        if path.is_file() and path.suffix in extensions and '__pycache__' not in path.parts:
            sources[path.relative_to(root).as_posix()] = path


def archive(target, folder, files, *, checksums=True):
    hashes = []
    with zipfile.ZipFile(target, 'w') as bundle:
        def write(name, data):
            entry = zipfile.ZipInfo(folder+'/'+name, (2026, 11, 17, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            bundle.writestr(entry, data, compresslevel=9)
        for name, path in sorted(files.items()):
            data = path.read_bytes()
            hashes.append(f'{hashlib.sha256(data).hexdigest()}  {name}')
            write(name, data)
        if checksums:
            write('SHA256SUMS', ('\n'.join(hashes)+'\n').encode('utf-8'))
    with zipfile.ZipFile(target) as bundle:
        if bundle.testzip() is not None:
            raise ValueError('ZIP integrity check failed')


def resource_path(path):
    return path.resolve().as_posix()


def build_setup(build):
    runtime = dist/exe
    source_name = prefix+'-Source.zip'
    source = build/source_name
    archive(source, prefix+'-Source', sources)
    (build/'data.rc').write_text(
        f'101 RCDATA "{resource_path(runtime)}"\n102 RCDATA "{resource_path(source)}"\n', encoding='utf-8')
    (build/'launcher.rc').write_text(
        f'1 ICON "{resource_path(root/"assets/setup.ico")}"\n1 24 "launcher.manifest"\n', encoding='utf-8')
    (build/'launcher.manifest').write_text(
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">'
        '<trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges>'
        '<requestedExecutionLevel level="asInvoker" uiAccess="false"/>'
        '</requestedPrivileges></security></trustInfo></assembly>\n', encoding='ascii')
    digests = []
    for name, path in [('runtime', runtime), ('source', source)]:
        values = ', '.join(f'0x{byte:02x}' for byte in hashlib.sha256(path.read_bytes()).digest())
        digests.append(f'constexpr std::array<unsigned char, 32> {name} = {{{values}}};')
    (build/'setup_data.hpp').write_text(
        '\n'.join(['#pragma once', '#include <array>', 'namespace setup_data {', *digests,
                   f'constexpr wchar_t source_filename[] = L"{source_name}";', '}'])+'\n', encoding='ascii')
    for name in ('data', 'launcher'):
        subprocess.run(['llvm-rc', '/fo', name+'.res', name+'.rc'], cwd=build, check=True)
    subprocess.run(['ld.lld.exe', '-flavor', 'link', '/dll', '/noentry', '/machine:x64',
                    f'/out:{dll}', 'data.res'], cwd=build, check=True)
    subprocess.run(['clang++', '-std=c++20', '-O2', '-Wall', '-Wextra', '-static', '-municode', '-mwindows',
                    '-I.', str(root/'src/installer_bootstrap.cpp'), 'launcher.res',
                    '-lbcrypt', '-lole32', '-luser32', '-o', exe], cwd=build, check=True)


def publish(staged):
    digest = hashlib.sha256(staged.read_bytes()).hexdigest()
    staged.replace(dist/staged.name)
    (dist/(staged.name+'.sha256')).write_text(f'{digest}  {staged.name}\n', encoding='ascii')
    print(f'{staged.name}  {digest}')


with tempfile.TemporaryDirectory(dir=dist) as temporary:
    build = Path(temporary)
    build_setup(build)
    normal = build/(prefix+'.zip')
    archive(normal, prefix, {exe:build/exe, dll:build/dll}, checksums=False)
    console = 'DetroitAdaptiveDisplay-Patch.exe'
    portable = build/(prefix+'-Portable.zip')
    archive(portable, prefix+'-Portable', {console:dist/console, 'LEEME.md':root/'docs/PARCHE_PORTATIL.md'})
    publish(normal)
    publish(portable)
