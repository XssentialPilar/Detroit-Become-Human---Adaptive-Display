"""Read-only AVM2 inspection of locally extracted UI resources.

Format reference: Adobe avmplus/doc/abcFormat-46-16.txt; opcode names and
operand counts: Adobe avmplus/core/opcodes.tbl (saved in analysis/reference).
Does not execute ActionScript or modify game resources.
"""
import argparse
import json
import re
import struct
import zlib
from pathlib import Path

class Reader:
    def __init__(self, data): self.data, self.pos = data, 0
    def take(self, size):
        if size < 0 or self.pos + size > len(self.data): raise ValueError('Truncated ABC')
        out = self.data[self.pos:self.pos + size]; self.pos += size; return out
    def byte(self): return self.take(1)[0]
    def var(self):
        out = 0
        for n in range(5):
            b = self.byte(); out |= (b & 127) << (7*n)
            if not b & 128: return out & 0xffffffff
        raise ValueError('Unterminated variable integer')
    def vector(self, fn): return [fn() for _ in range(self.var())]
    def pool(self, zero, fn): return [zero] + [fn() for _ in range(max(0,self.var()-1))]

class ABC:
    def __init__(self, data):
        r = self.r = Reader(data)
        self.minor,self.major = struct.unpack('<HH',r.take(4))
        if (self.major,self.minor)!=(46,16): raise ValueError(f'Unsupported ABC {self.major}.{self.minor}')
        self.ints = r.pool(0,r.var)
        self.uints = r.pool(0,r.var)
        self.doubles = r.pool(float('nan'),lambda:struct.unpack('<d',r.take(8))[0])
        self.string_positions = [None]
        self.strings = r.pool('',self.string)
        self.namespaces = r.pool((0,0),lambda:(r.byte(),r.var()))
        self.nssets = r.pool([],lambda:r.vector(r.var))
        self.names = r.pool((0,[]),self.multiname)
        self.methods = r.vector(self.method)
        self.metadata = r.vector(self.meta)
        self.labels = {}
        self.classes = r.vector(self.instance)
        for cls in self.classes:
            init = r.var(); self.labels[init] = cls['name']+'::<static>'
            cls['static_traits'] = self.traits(cls['name']+'::<static>')
        for i in range(r.var()):
            init = r.var(); self.labels[init] = f'script{i}::<init>'; self.traits(f'script{i}')
        self.bodies = r.vector(self.body)
        if r.pos != len(data): raise ValueError(f'Unexpected trailing ABC bytes: {len(data)-r.pos}')
    def string(self):
        r=self.r;start=r.pos;size=r.var();value=r.take(size).decode('utf-8')
        self.string_positions.append((start,r.pos));return value
    def multiname(self):
        r=self.r;k=r.byte()
        if k in (7,13,9,14): args=[r.var(),r.var()]
        elif k in (15,16,27,28): args=[r.var()]
        elif k in (17,18): args=[]
        elif k==29: args=[r.var(),*r.vector(r.var)]
        else: raise ValueError(f'Unknown multiname {k}')
        return k,args
    def name(self,index):
        if not index:return '*'
        k,a=self.names[index]
        if k in (7,13):
            ns=self.strings[self.namespaces[a[0]][1]]
            return (ns+'::' if ns else '')+self.strings[a[1]]
        if k in (9,14,15,16):return self.strings[a[0]]
        if k==29:return self.name(a[0])+'<'+','.join(self.name(x) for x in a[1:])+'>'
        return f'<dynamic:{index}>'
    def method(self):
        r=self.r;params=r.var();ret=r.var();types=[r.var() for _ in range(params)];name=r.var();flags=r.byte()
        opts=r.vector(lambda:(r.var(),r.byte())) if flags&8 else []
        names=[r.var() for _ in range(params)] if flags&128 else []
        return dict(params=types,returns=ret,name=name,flags=flags,optional=opts,param_names=names)
    def meta(self):
        r=self.r;name=r.var();n=r.var();return name,[r.var() for _ in range(n)],[r.var() for _ in range(n)]
    def traits(self,owner):
        r=self.r;out=[]
        for _ in range(r.var()):
            name=self.name(r.var());flags=r.byte();kind=flags&15
            if kind in (0,6):
                a=[r.var(),r.var(),r.var()]
                if a[2]:a.append(r.byte())
            elif kind in (1,2,3,4,5):
                a=[r.var(),r.var()]
                if kind in (1,2,3,5):self.labels[a[1]]=owner+'::'+name
            else:raise ValueError(f'Unknown trait {kind}')
            meta=r.vector(r.var) if flags&64 else []
            out.append(dict(name=name,kind=kind,args=a,metadata=meta))
        return out
    def instance(self):
        r=self.r;name=self.name(r.var());base=self.name(r.var());flags=r.byte()
        if flags&8:r.var()
        interfaces=r.vector(r.var);init=r.var();self.labels[init]=name+'::<init>'
        return dict(name=name,base=base,flags=flags,interfaces=interfaces,traits=self.traits(name))
    def body(self):
        r=self.r;method=r.var();stack=r.var();regs=r.var();depth=r.var();scope=r.var();length_offset=r.pos;length=r.var();offset=r.pos;code=r.take(length)
        exceptions=r.vector(lambda:[r.var() for _ in range(5)])
        traits=self.traits(f'method{method}')
        return dict(method=method,name=self.labels.get(method,self.strings[self.methods[method]['name']]),
                    max_stack=stack,locals=regs,scope_depth=depth,max_scope=scope,
                    offset=offset,length_offset=length_offset,code=code,exceptions=exceptions,traits=traits)
    def disassemble(self,body,ops):
        r=Reader(body['code']);out=[]
        names={4,5,0x45,0x46,0x4a,0x4c,0x4e,0x4f,0x59,0x5d,0x5e,0x5f,0x60,0x61,0x66,0x68,0x6a,0x80,0x86,0xb2}
        while r.pos<len(r.data):
            start=r.pos;op=r.byte()
            if op not in ops:raise ValueError(f'Unknown opcode {op:x} at {start:x}')
            count,name=ops[op];args=[]
            def s24():return int.from_bytes(r.take(3),'little',signed=True)
            if 0x0c<=op<=0x1a:
                off=s24();args=[r.pos+off]
            elif op==0x1b:
                default=s24();n=r.var();args=[start+default,*[start+s24() for _ in range(n+1)]]
            elif op in (0x24,0x65):args=[r.byte()]
            elif op==0xef:args=[r.byte(),r.var(),r.byte(),r.var()]
            else:args=[r.var() for _ in range(count)]
            note=''
            if args:
                if op in names:note=self.name(args[0])
                elif op in (0x2c,0xf1):note=repr(self.strings[args[0]])
                elif op==0x2f:note=str(self.doubles[args[0]])
                elif op==0x2d:note=str(self.ints[args[0]])
                elif op==0x2e:note=str(self.uints[args[0]])
            out.append(dict(offset=start,absolute=body['offset']+start,length=r.pos-start,opcode=op,
                            instruction=name,args=args,note=note))
        return out

def opcode_table():
    text=(Path(__file__).parent / 'reference/opcodes.tbl').read_text()
    return {int(hexop,16):(int(n),name) for n,name,hexop in re.findall(r'ABC_OP\(\s*(\d+),[^\n]*?,\s*(\w+)\)\s*//\s*(0x[0-9A-Fa-f]+)',text)}

def abc_blocks(resource):
    metadata=next(x for x in json.loads(Path('analysis/ui_signatures.json').read_text()) if x['id']==resource)
    raw=Path(f'analysis/ui/{resource}.bin').read_bytes()
    for sig in metadata['signatures']:
        off=sig['offset'];length=sig['length']
        if sig['magic'] not in ('FWS','GFX','CWS','CFX'):continue
        b=raw[off:off+length]
        if sig['magic'] in ('CWS','CFX'):
            try:b=raw[off:off+8]+zlib.decompress(raw[off+8:])
            except zlib.error:continue
        if len(b)!=length:continue
        bits=b[8]>>3;p=8+(5+4*bits+7)//8+4
        while p+2<=len(b):
            head=struct.unpack_from('<H',b,p)[0];p+=2;kind,size=head>>6,head&63
            if size==63:size=struct.unpack_from('<I',b,p)[0];p+=4
            if p+size>len(b):raise ValueError('Invalid SWF tag')
            if kind==82:
                q=b.index(0,p+4,p+size)+1
                yield dict(resource=resource,resource_name=metadata['name'],swf_offset=off,abc_offset=q,data=b[q:p+size])
            p+=size
            if not kind:break

