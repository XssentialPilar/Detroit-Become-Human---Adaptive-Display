"""Append-only ABC editor for owned responsive UI prototypes.

Preserves existing pool/method indices. This is deliberately separate from the
production FPS builder. No game installation or process writes are performed.
"""
import struct
from inspect_abc import ABC, Reader, opcode_table

def var(n):
    n &= 0xffffffff; out=bytearray()
    while n>127: out.append((n&127)|128); n>>=7
    out.append(n); return bytes(out)

class LocatedABC(ABC):
    def __init__(self,data):
        self.method_spans=[];self.body_spans=[];self.trait_spans={}
        super().__init__(data)
    def method(self):
        start=self.r.pos; value=super().method();self.method_spans.append((start,self.r.pos));return value
    def body(self):
        start=self.r.pos; value=super().body();self.body_spans.append((start,self.r.pos));return value
    def traits(self,owner):
        r=self.r; start=r.pos;count=r.var();header_end=r.pos; names=[]
        # Locate each trait's actual multiname index, retaining private namespaces.
        for _ in range(count):
            name=r.var();flags=r.byte();kind=flags&15;names.append(name)
            if kind in (0,6):
                r.var();r.var();v=r.var()
                if v:r.byte()
            elif kind in (1,2,3,4,5):r.var();r.var()
            else:raise ValueError(kind)
            if flags&64:r.vector(r.var)
        end=r.pos;r.pos=start;value=super().traits(owner)
        self.trait_spans[owner]=(start,header_end,end,names)
        return value

class Editor:
    def __init__(self,data):
        self.old=data;self.abc=a=LocatedABC(data);self.edits=[]
        r=Reader(data);r.take(4);self.pools={}
        def pool(label,fn):
            start=r.pos;n=r.var();header=r.pos
            for _ in range(max(0,n-1)):fn()
            self.pools[label]=(start,header,r.pos,n)
        pool('ints',r.var);pool('uints',r.var);pool('doubles',lambda:r.take(8))
        pool('strings',lambda:r.take(r.var()));pool('namespaces',lambda:(r.byte(),r.var()))
        pool('nssets',lambda:r.vector(r.var))
        def mn():
            k=r.byte()
            if k in (7,13,9,14):r.var();r.var()
            elif k in (15,16,27,28):r.var()
            elif k in (17,18):pass
            elif k==29:r.var();r.vector(r.var)
            else:raise ValueError(k)
        pool('names',mn)
        self.extra_strings=[];self.extra_names=[];self.extra_methods=[];self.extra_bodies=[]
        self.extra_traits={}
        self.public_ns=next(i for i,(kind,name) in enumerate(a.namespaces) if kind==0x16 and a.strings[name]=='')
    def string(self,value):
        if value in self.abc.strings:return self.abc.strings.index(value)
        if value not in self.extra_strings:self.extra_strings.append(value)
        return len(self.abc.strings)+self.extra_strings.index(value)
    def public(self,value):
        s=self.string(value);entry=(7,[self.public_ns,s])
        if entry in self.abc.names:return self.abc.names.index(entry)
        if entry not in self.extra_names:self.extra_names.append(entry)
        return len(self.abc.names)+self.extra_names.index(entry)
    def name(self,value):
        matches=[i for i in range(1,len(self.abc.names)) if self.abc.name(i)==value]
        if not matches:raise ValueError('Missing multiname '+value)
        return matches[0]
    def trait(self,owner,name):
        names=self.abc.trait_spans[owner][3]
        return next(i for i in names if self.abc.name(i)==name)
    def replace_body(self,method,code):
        b=next(b for b in self.abc.bodies if b['method']==method)
        self.edits.append((b['length_offset'],b['offset']+len(b['code']),var(len(code))+code))
    def append_before_return(self,method,code):
        b=next(b for b in self.abc.bodies if b['method']==method)
        if b['exceptions'] or b['code'][-1:]!=b'\x47':raise ValueError('Unsafe append')
        # Original branches to the terminal return now land on the inserted code.
        # No prior offsets or relative branch distances change.
        self.replace_body(method,b['code'][:-1]+code+b'\x47')
    def add_method(self,owner,name,code,scope_depth,locals_count=16,optional_event=True,override=False):
        index=len(self.abc.methods)+len(self.extra_methods)
        method_name=self.public(name)
        # One optional untyped event argument: valid for direct and event calls.
        # Match the game's own null-default encoding (value=12, kind=Null=12).
        self.extra_methods.append((var(1)+var(self.name('void'))+var(0)+var(self.string(name))+b'\x08'+var(1)+var(12)+b'\x0c') if optional_event else (var(0)+var(self.name('void'))+var(self.string(name))+b'\x00'))
        self.extra_traits.setdefault(owner,[]).append(var(method_name)+bytes([0x21 if override else 0x01])+var(0)+var(index))
        self.extra_bodies.append(var(index)+var(16)+var(locals_count)+var(scope_depth)+var(scope_depth+1)+var(len(code))+code+var(0)+var(0))
        return index,method_name
    def add_slot(self,owner,name,type_name='*'):
        # AVM2 Trait_Slot, auto-assigned slot_id=0, any type, no default.
        # Existing classes are sealed; caching requires declared traits.
        index=self.public(name)
        self.extra_traits.setdefault(owner,[]).append(var(index)+b'\x00'+var(0)+var(0 if type_name=='*' else self.name(type_name))+var(0))
        return index
    def finish(self):
        a=self.abc
        def extend_pool(label,extra):
            if not extra:return
            start,header,end,count=self.pools[label]
            self.edits.extend([(start,header,var(count+len(extra))),(end,end,b''.join(extra))])
        extend_pool('strings',[var(len(s.encode()))+s.encode() for s in self.extra_strings])
        extend_pool('names',[bytes([k])+b''.join(var(x) for x in args) for k,args in self.extra_names])
        for spans,items,count in [(a.method_spans,self.extra_methods,len(a.methods)),(a.body_spans,self.extra_bodies,len(a.bodies))]:
            if items:
                start=spans[0][0]-len(var(count));end=spans[-1][1]
                self.edits.extend([(start,spans[0][0],var(count+len(items))),(end,end,b''.join(items))])
        for owner,traits in self.extra_traits.items():
            start,header,end,names=a.trait_spans[owner]
            self.edits.extend([(start,header,var(len(names)+len(traits))),(end,end,b''.join(traits))])
        result=self.old
        for start,end,code in sorted(self.edits,reverse=True):result=result[:start]+code+result[end:]
        parsed=ABC(result)
        for b in parsed.bodies:parsed.disassemble(b,opcode_table())
        return result,parsed

class Code:
    def __init__(self):self.data=bytearray();self.labels={};self.branches=[]
    def op(self,opcode,*args):
        self.data.append(opcode)
        for n in args:self.data.extend(var(n))
        return self
    def num(self,n):return self.op(0x25,n)
    def get(self,n):return self.op(0x62,n)
    def put(self,n):return self.op(0x63,n)
    def label(self,name):self.labels[name]=len(self.data);return self
    def branch(self,opcode,label):
        self.data.append(opcode);self.branches.append((len(self.data),label));self.data.extend(b'\0'*3);return self
    def finish(self):
        for pos,label in self.branches:self.data[pos:pos+3]=(self.labels[label]-pos-3).to_bytes(3,'little',signed=True)
        return bytes(self.data)
