"""Read or rebuild a length-prefixed GFx movie inside its game resource."""
import struct

ROOT='comData::MENU_OPTIONS_PC'
BASE='comData::MENU_OPTIONS_01'
PAGE='comData.menu_options_01.pages::MenuOptionsPage'

def extract(src):
    off=369
    if src[off:off+3]!=b'GFX':raise ValueError('Unexpected FPS UI SWF offset')
    n=struct.unpack_from('<I',src,off+4)[0];swf=src[off:off+n]
    p=8+(5+4*(swf[8]>>3)+7)//8+4
    while p+2<len(swf):
        h=struct.unpack_from('<H',swf,p)[0];p+=2;size=h&63
        if size==63:size=struct.unpack_from('<I',swf,p)[0];p+=4
        if h>>6==82:
            q=swf.index(0,p+4,p+size)+1
            return dict(swf_offset=off,abc_offset=q,data=swf[q:p+size])
        p+=size
    raise ValueError('No ABC block')

def repack(src,block,new):
    off=block['swf_offset'];abc_off=block['abc_offset'];old=block['data']
    size=struct.unpack_from('<I',src,off+4)[0];swf=bytearray(src[off:off+size])
    if swf[:3] not in (b'GFX',b'FWS'):raise ValueError('Unsupported compressed resource')
    p=8+(5+4*(swf[8]>>3)+7)//8+4
    while p+2<len(swf):
        tag=struct.unpack_from('<H',swf,p)[0];p+=2;n=tag&63;length_at=p
        if n==63:n=struct.unpack_from('<I',swf,p)[0];p+=4
        if tag>>6==82 and p<=abc_off<p+n:break
        p+=n
    if tag&63!=63 or abc_off+len(old)!=p+n:raise ValueError('Unexpected ABC container')
    swf[abc_off:abc_off+len(old)]=new
    struct.pack_into('<I',swf,length_at,n+len(new)-len(old));struct.pack_into('<I',swf,4,len(swf))
    result=bytearray(src[:off]+swf+src[off+size:])
    wrapper=src.find(b'MENU_RES');size_at=wrapper+12;payload_at=wrapper+16
    if wrapper<0 or struct.unpack_from('<I',src,size_at)[0]!=len(src)-payload_at:raise ValueError('Unexpected resource wrapper')
    struct.pack_into('<I',result,size_at,len(result)-payload_at);struct.pack_into('<I',result,off-4,len(swf))
    return bytes(result)

