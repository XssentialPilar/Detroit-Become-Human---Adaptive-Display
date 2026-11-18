"""Build this project's persistent WinMM proxy and verify its export contract."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import pefile

ROOT=Path(__file__).resolve().parent
def run(*args):
    subprocess.run(args,cwd=ROOT,check=True)
def main():
    run(sys.executable,'generate_native_loader.py')
    profile = json.loads((ROOT/'release.json').read_text(encoding='utf8'))['engine_image']
    header = ROOT/'build/native/engine_profile.hpp'
    header.write_text('\n'.join([
        '#pragma once', 'namespace engine_profile {',
        *(f'constexpr unsigned {key} = {profile[key]};' for key in ('size','timestamp','checksum','certificate')),
        f'constexpr char sha256[] = "{profile["sha256"]}";', '}',
    ]), encoding='ascii')
    run('clang++','-std=c++20','-O2','-Wall','-Wextra','-shared','-static','-static-libgcc',
        '-Ibuild/native','-Iinclude','src/native_loader.cpp','src/native_transaction.cpp',
        'src/native_display.cpp','src/native_video.cpp','src/native_ui_contract.cpp','src/native_ui_transform.cpp','src/ui_diagnostics.cpp',
        'src/camera_native.S','build/native/winmm_stubs.S','build/native/winmm.def',
        '-lbcrypt','-luser32','-o','build/native/winmm.dll')
    output=ROOT/'build/native/winmm.dll'
    system=Path(os.environ['SystemRoot'])/'System32/winmm.dll'
    def exports(path):
        return {(x.ordinal,x.name) for x in pefile.PE(str(path)).DIRECTORY_ENTRY_EXPORT.symbols}
    if exports(output)!=exports(system):raise RuntimeError('WinMM export/ordinal contract differs')
    pe=pefile.PE(str(output))
    imports=[i.dll.decode() for i in pe.DIRECTORY_ENTRY_IMPORT]
    if not pe.OPTIONAL_HEADER.DATA_DIRECTORY[3].Size:raise RuntimeError('Missing x64 unwind directory')
    result={'version':'0.8.3-anchors','sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
            'hook_count':10,
            'export_count':len(exports(output)),'system_exports_and_ordinals_match':True,
            'imports':imports,'unwind_directory_present':True,'runtime_validated':False}
    (ROOT/'build/native/manifest.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
