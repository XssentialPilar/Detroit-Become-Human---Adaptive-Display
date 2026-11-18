"""Build a custom 30/60/90/144/Unlimited options resource from the local game.

Only prepares workspace artifacts. Installation is a separate, reversible step.
Reuses the game's existing MenuChoiceData and native iFPS enum (0 through 4).
"""
import hashlib
import json
import struct
from pathlib import Path
from inspect_abc import ABC,abc_blocks,opcode_table
from fps_localization import UI_KEY, build_localization

def var(n):
    b=bytearray()
    while n>127:b.append((n&127)|128);n>>=7
    b.append(n);return bytes(b)
def digest(b):return hashlib.sha256(b).hexdigest()
def build():
    src=Path('analysis/ui/217.bin').read_bytes();blocks=list(abc_blocks(217))
    if len(blocks)!=1:raise RuntimeError('Expected one ABC block')
    block=blocks[0];old=block['data'];abc=ABC(old);ops=opcode_table()
    body=next(x for x in abc.bodies if x['name'].endswith('MenuOptionsPageVideoPC::addBasicOptions'))
    code=body['code']
    if len(code)!=423 or code[0xda:0xdc]!=b'\x24\x02':raise RuntimeError('Unexpected PC options method')
    instructions=abc.disassemble(body,ops)
    if body['exceptions'] or any(0x0c<=x['opcode']<=0x1b for x in instructions):raise RuntimeError('Method needs branch relocation')
    # Construct the same choice objects as the original two entries.
    template=code[0xee:0xfe]
    if template.hex()!='2a24015d472c971e24014a470261ec18':raise RuntimeError('Choice template mismatch')
    extras=[]
    for enum,label in [(2,'90'),(3,'144'),(4,'Unlimited')]:
        index=abc.strings.index(label)
        extras.append(b'\x2a\x24'+bytes([enum])+b'\x5d\x47\x2c'+var(index)+b'\x24'+bytes([enum])+b'\x4a\x47\x02\x61'+var(3180))
    newcode=code[:0xdb]+b'\x05'+code[0xdc:0xfe]+b''.join(extras)+code[0xfe:]
    label_index=abc.strings.index('Unlimited');start,end=abc.string_positions[label_index]
    localized=next(x for x in abc.bodies if x['name'].endswith('MenuOptionsPageVideoPC::onLocalize'))
    if localized['exceptions'] or localized['code'][-1:]!=b'\x47' or any(0x0c<=x['opcode']<=0x1b for x in abc.disassemble(localized,ops)):
        raise RuntimeError('Localization method needs branch relocation')
    # Match the existing advanced controls: recalculate choice layout after a
    # language change. All fonts and translations still come from the game.
    newlocalized=localized['code'][:-1]+b'\xd0\x66'+var(1955)+b'\x4f'+var(1827)+b'\x00\x47'
    label_bytes=UI_KEY.encode('utf-8')
    edits=[(body['length_offset'],body['offset']+len(code),var(len(newcode))+newcode),
           (localized['length_offset'],localized['offset']+len(localized['code']),var(len(newlocalized))+newlocalized),
           (start,end,var(len(label_bytes))+label_bytes)]
    new=old
    for start,end,replacement in sorted(edits,reverse=True):new=new[:start]+replacement+new[end:]
    parsed=ABC(new)
    if len(parsed.bodies)!=len(abc.bodies) or len(parsed.classes)!=len(abc.classes):raise RuntimeError('ABC structure changed unexpectedly')
    changed=[]
    for a,b in zip(abc.bodies,parsed.bodies):
        parsed.disassemble(b,ops)
        if a['code']!=b['code']:changed.append(a['method'])
    if set(changed)!={body['method'],localized['method']}:raise RuntimeError('Unexpected method changes')
    expected_strings=list(abc.strings);expected_strings[label_index]=UI_KEY
    if parsed.strings!=expected_strings:raise RuntimeError('Unexpected string changes')
    off=block['swf_offset'];abc_off=block['abc_offset'];old_swf_size=struct.unpack_from('<I',src,off+4)[0]
    swf=bytearray(src[off:off+old_swf_size]);p=8+(5+4*(swf[8]>>3)+7)//8+4
    while p+2<=len(swf):
        head=struct.unpack_from('<H',swf,p)[0];p+=2;size=head&63;typ=head>>6;size_offset=p
        if size==63:size=struct.unpack_from('<I',swf,p)[0];p+=4
        if typ==82 and p<=abc_off<p+size:break
        p+=size
    else:raise RuntimeError('DoABC tag missing')
    if head&63!=63 or abc_off+len(old)!=p+size:raise RuntimeError('Unexpected DoABC encoding')
    delta=len(new)-len(old)
    swf[abc_off:abc_off+len(old)]=new
    struct.pack_into('<I',swf,size_offset,size+delta);struct.pack_into('<I',swf,4,len(swf))
    result=bytearray(src[:off]+swf+src[off+old_swf_size:])
    if src[261:269]!=b'MENU_RES' or struct.unpack_from('<I',src,273)[0]!=len(src)-277:raise RuntimeError('MENU_RES layout mismatch')
    struct.pack_into('<I',result,273,len(result)-277);struct.pack_into('<I',result,off-4,len(swf))
    out=Path('build/fps_menu');out.mkdir(parents=True,exist_ok=True)
    (out/'217.bin').write_bytes(result)
    localization_resource,localization_report=build_localization(out)
    ui_resource={'type':18002,'id':217,'name':'MENU_OPTIONS_PC.gfx','path':str((out/'217.bin').resolve()),
                 'original_sha256':digest(src),'modified_sha256':digest(result),'original_size':len(src),'modified_size':len(result)}
    manifest={'resource':217,'name':'MENU_OPTIONS_PC.gfx','original_sha256':digest(src),'modified_sha256':digest(result),
              'original_size':len(src),'modified_size':len(result),'method':body['name'],
              'choices':[{'label':x,'native_enum':i} for i,x in enumerate(['30','60','90','144',UI_KEY])],
              'resources':[ui_resource,localization_resource],
              'localization':{'key':UI_KEY,'language_count':localization_report['language_count'],
                              'spanish_label':'SIN LÍMITE','report':str((out/'localization.json').resolve()),
                              'dynamic_language_change':True,'reposition_after_language_change':True},
              'validation':{'abc_reparsed':True,'all_methods_disassembled':True,'only_menu_and_localization_layout_methods_changed':True,
                            'all_25_localizations_verified':True},
              'runtime_validated':False,'native_unlimited_note':'Executable describes native mode 4 as Unlimited (Max 1000 FPS).'}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2));print(json.dumps(manifest,indent=2))
    return result
if __name__=='__main__':build()
