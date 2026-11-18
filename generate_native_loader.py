"""Generate WinMM forwarding stubs from the installed Windows DLL export table.

Every original export is forwarded to System32. No third-party loader is used.
The generated source contains names/ordinals, not code copied from Windows.
"""
import json
import os
from pathlib import Path
import pefile
out=Path('build/native');out.mkdir(parents=True,exist_ok=True)
system=Path(os.environ['SystemRoot'])/'System32/winmm.dll'
pe=pefile.PE(str(system))
exports=sorted(pe.DIRECTORY_ENTRY_EXPORT.symbols,key=lambda x:x.ordinal)
assembly=['.intel_syntax noprefix','.text']
defs=['LIBRARY winmm','EXPORTS']
for i,e in enumerate(exports):
    label=f'proxy_winmm_{e.ordinal}';name=e.name.decode('ascii') if e.name else None
    defs.append(f'  {name or label}={label} @{e.ordinal}'+(' NONAME' if name is None else ''))
    assembly += [f'.global {label}',f'{label}:',f'  jmp qword ptr [rip + winmm_api_table + {i*8}]',
                 f'.seh_proc slow_{i}',f'slow_{i}:','  sub rsp, 0xa8','  .seh_stackalloc 0xa8','  .seh_endprologue']
    for n in range(4):assembly.append(f'  movdqu [rsp + {0x20+n*16}], xmm{n}')
    for n,reg in enumerate(['rcx','rdx','r8','r9','r10','r11']):assembly.append(f'  mov [rsp + {0x60+n*8}], {reg}')
    assembly += [f'  mov ecx, {i}','  call resolve_winmm']
    for n in range(4):assembly.append(f'  movdqu xmm{n}, [rsp + {0x20+n*16}]')
    for n,reg in enumerate(['rcx','rdx','r8','r9','r10','r11']):assembly.append(f'  mov {reg}, [rsp + {0x60+n*8}]')
    assembly += ['  add rsp, 0xa8','  jmp rax','.seh_endproc']
assembly += ['.data','.balign 8','.global winmm_api_table','winmm_api_table:']
assembly += [f'  .quad slow_{i}' for i in range(len(exports))]
names=',\n'.join('  '+(json.dumps(e.name.decode('ascii')) if e.name else 'nullptr') for e in exports)
ordinals=','.join(str(e.ordinal) for e in exports)
(out/'winmm_stubs.S').write_text('\n'.join(assembly)+'\n')
(out/'winmm.def').write_text('\n'.join(defs)+'\n')
(out/'winmm_exports.hpp').write_text(f'#pragma once\ninline constexpr unsigned winmm_export_count={len(exports)};\ninline constexpr const char* winmm_export_names[]={{\n{names}\n}};\ninline constexpr unsigned winmm_export_ordinals[]={{{ordinals}}};\n')
print('Generated',len(exports),'WinMM forwarders; camera code is linked with SEH metadata')
