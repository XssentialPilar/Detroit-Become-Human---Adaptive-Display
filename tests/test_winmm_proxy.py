"""Exercise forwarding in a short-lived non-game process, never inject a game."""
import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import Path
import subprocess
import sys
import unittest
import pefile

ROOT=Path(__file__).resolve().parents[1]
DLL=ROOT/'bin/winmm.dll'
SYSTEM=Path(os.environ['SystemRoot'])/'System32/winmm.dll'

def probe():
    proxy=C.WinDLL(str(DLL));system=C.WinDLL(str(SYSTEM))
    for lib in (proxy,system):
        lib.timeGetTime.restype=W.DWORD
        lib.timeGetDevCaps.argtypes=[C.c_void_p,W.UINT];lib.timeGetDevCaps.restype=W.UINT
        lib.timeBeginPeriod.argtypes=[W.UINT];lib.timeBeginPeriod.restype=W.UINT
        lib.timeEndPeriod.argtypes=[W.UINT];lib.timeEndPeriod.restype=W.UINT
    before=system.timeGetTime();now=proxy.timeGetTime();after=system.timeGetTime()
    assert ((now-before)&0xffffffff)<=((after-before)&0xffffffff)
    cap1=(W.UINT*2)();cap2=(W.UINT*2)()
    assert proxy.timeGetDevCaps(cap1,C.sizeof(cap1))==system.timeGetDevCaps(cap2,C.sizeof(cap2))==0
    assert list(cap1)==list(cap2)
    assert proxy.timeBeginPeriod(cap1[0])==0
    assert proxy.timeEndPeriod(cap1[0])==0
    assert proxy.waveOutGetNumDevs()==system.waveOutGetNumDevs()
    assert proxy.midiOutGetNumDevs()==system.midiOutGetNumDevs()
    print('Timer/capability/device forwarding passed')

class WinmmProxyTests(unittest.TestCase):
    def test_export_names_and_ordinals(self):
        def exports(path):
            return {(e.ordinal,e.name) for e in pefile.PE(str(path)).DIRECTORY_ENTRY_EXPORT.symbols}
        self.assertEqual(exports(DLL),exports(SYSTEM))
    def test_real_calls_in_child_process(self):
        p=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--probe'],capture_output=True,text=True,timeout=20)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn('forwarding passed',p.stdout)

if __name__=='__main__':
    if '--probe' in sys.argv:probe()
    else:unittest.main()
