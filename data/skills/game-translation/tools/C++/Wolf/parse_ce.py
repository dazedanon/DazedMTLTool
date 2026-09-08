import struct, sys, collections

path = r"C:\Users\sw\Desktop\Wolf\Data\BasicData\CommonEvent.dat"
data = open(path,'rb').read()
# Check encryption: first byte
print("first byte:", data[0])

class R:
    def __init__(self, b, off=0):
        self.b=b; self.i=off
    def byte(self):
        v=self.b[self.i]; self.i+=1; return v
    def i32(self):
        v=struct.unpack_from('<i', self.b, self.i)[0]; self.i+=4; return v
    def raw(self,n):
        v=self.b[self.i:self.i+n]; self.i+=n; return v
    def string(self):
        size=self.i32()
        s=self.b[self.i:self.i+size-1]; self.i+=size
        # last byte null
        try:
            return s.decode('cp932')
        except:
            return s.decode('latin1')

r=R(data)
# magic 00 57 00 00 4F 4C 00 46 43 00 8F  (11 bytes)
magic = r.raw(11)
print("magic:", magic.hex())
nevents = r.i32()
print("nevents:", nevents)

CID_NAMES={102:'Choices',111:'VarCond',112:'StrCond',121:'SetVar',122:'SetStr',
 210:'CommonEvent',211:'CommonEventReserve',300:'CommonEventByName',
 401:'ChoiceCase',402:'SpecialChoiceCase',420:'ElseCase',421:'CancelCase',101:'Message'}

INNER_MAGIC=b'\x0a\x00\x00\x00'

def read_command(r):
    nargs = r.byte()-1
    cid = r.i32()
    args=[r.i32() for _ in range(nargs)]
    indent=r.byte()
    nstr=r.byte()
    strs=[r.string() for _ in range(nstr)]
    term=r.byte()
    move=None
    if term==0x01:
        # move command: 5 unknown, flag, route count, routes
        unk=r.raw(5); flags=r.byte(); rc=r.i32()
        routes=[]
        for _ in range(rc):
            rid=r.byte(); rn=r.byte(); rargs=[r.i32() for _ in range(rn)]
            rterm=r.raw(2)
            routes.append((rid,rargs))
        move=routes
    elif term!=0x00:
        raise Exception("bad term %d at %d"%(term,r.i))
    return (cid,args,indent,strs,move)

samples=collections.defaultdict(list)
for e in range(nevents):
    ind=r.byte()
    assert ind==0x8E, (e,ind,r.i)
    eid=r.i32(); u1=r.i32(); u2=r.raw(7); name=r.string()
    ncmd=r.i32()
    cmds=[]
    for c in range(ncmd):
        cmd=read_command(r)
        cmds.append(cmd)
        cid=cmd[0]
        if cid in (102,111,112,210,211,300,401,421,402,420,121,122):
            if len(samples[cid])<8:
                samples[cid].append((eid,cmd))
    # rest of event
    u11=r.string(); desc=r.string()
    ind=r.byte(); assert ind==0x8F,(e,ind,r.i)
    r.raw(4) # inner magic 0a000000
    for _ in range(10): r.string()
    r.raw(4)
    for _ in range(10): r.byte()
    r.raw(4)
    for _ in range(10):
        n=r.i32()
        for _ in range(n): r.string()
    r.raw(4)
    for _ in range(10):
        n=r.i32()
        for _ in range(n): r.i32()
    r.raw(0x1D)
    for _ in range(100): r.string()
    ind=r.byte(); assert ind==0x91,(e,ind,r.i)
    r.string()
    ind=r.byte()
    if ind==0x91:
        continue
    assert ind==0x92,(e,ind,r.i)
    r.string(); r.i32(); ind=r.byte(); assert ind==0x92

print("final byte:", data[r.i] if r.i<len(data) else None, "pos",r.i,"len",len(data))

for cid in sorted(samples):
    print("\n==== CID %d %s ===="%(cid,CID_NAMES.get(cid,'?')))
    for eid,(c,args,indent,strs,move) in samples[cid]:
        print("  ev%d args=%s strs=%s"%(eid,args,strs))
