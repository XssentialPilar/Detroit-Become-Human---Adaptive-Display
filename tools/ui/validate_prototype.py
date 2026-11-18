"""Execute the layout instruction subset against synthetic UI objects."""
import math
from inspect_abc import opcode_table

def execute(a,body,root,arg=None):
    ins=a.disassemble(body,opcode_table());by={v['offset']:i for i,v in enumerate(ins)}
    regs=[None]*body['locals'];regs[0]=root
    if len(regs)>1:regs[1]=arg
    stack=[];pc=0;steps=0;maximum=0
    def key(n):return a.name(n).split('::')[-1]
    def get(obj,name):
        if isinstance(obj,list):return len(obj) if name=='length' else obj[int(name)]
        return obj[name]
    while True:
        steps+=1
        if steps>10000:raise AssertionError('Layout does not terminate')
        i=ins[pc];op=i['opcode'];args=i['args'];pc+=1
        if op==0x62:stack.append(regs[args[0]])
        elif op==0x63:regs[args[0]]=stack.pop()
        elif op==0x30:stack.pop()
        elif op==0x25:stack.append(args[0])
        elif op==0x2c:stack.append(a.strings[args[0]])
        elif op==0x2d:stack.append(a.ints[args[0]])
        elif op==0x20:stack.append(None)
        elif op==0x26:stack.append(True)
        elif op==0x27:stack.append(False)
        elif op==0x60:
            name=key(args[0])
            stack.append(dict(min=min,max=max,floor=math.floor,ceil=math.ceil) if name=='Math' else root['_classes'][name])
        elif op==0x66:
            name=stack.pop() if a.names[args[0]][0]==0x1b else key(args[0]);stack.append(get(stack.pop(),name))
        elif op==0x61:
            value=stack.pop();obj=stack.pop();obj[key(args[0])]=value
        elif op in (0x46,0x4f):
            values=[stack.pop() for _ in range(args[1])][::-1];obj=stack.pop();result=get(obj,key(args[0]))(*values)
            if op==0x46:stack.append(result)
        elif op in (0xa0,0xa1,0xa2,0xa3,0xa4):
            b=stack.pop();v=stack.pop();stack.append({0xa0:lambda:v+b,0xa1:lambda:v-b,0xa2:lambda:v*b,0xa3:lambda:v/b,0xa4:lambda:v%b}[op]())
        elif op==0x90:stack.append(-stack.pop())
        elif op==0x92:regs[args[0]]+=1
        elif op==0x10:pc=by[args[0]]
        elif op in (0x11,0x12):
            value=stack.pop()
            if bool(value)==(op==0x11):pc=by[args[0]]
        elif op==0xb2:
            obj=stack.pop();stack.append(isinstance(obj,dict) and obj.get('_type')==a.name(args[0]))
        elif op in (0x13,0x14,0x15,0x16,0x17,0x18):
            b=stack.pop();v=stack.pop()
            same=(v is b) if isinstance(v,(dict,list)) or isinstance(b,(dict,list)) else v==b
            branch=same if op==0x13 else not same if op==0x14 else v<b if op==0x15 else v<=b if op==0x16 else v>b if op==0x17 else v>=b
            if branch:pc=by[args[0]]
        elif op==0x47:
            assert stack==[],stack
            assert maximum<=body['max_stack'],maximum
            return dict(steps=steps,maximum_stack=maximum)
        else:raise AssertionError(f'Unsupported emitted opcode {op:x}')
        maximum=max(maximum,len(stack))

