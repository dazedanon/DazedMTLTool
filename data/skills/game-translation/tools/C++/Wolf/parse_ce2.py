import struct, collections

path = r"C:\Users\sw\Desktop\Wolf\Data\BasicData\CommonEvent.dat"
data = open(path,'rb').read()

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
        if size<=0 or size>100000: raise Exception("badstr %d"%size)
        s=self.b[self.i:self.i+size-1]; self.i+=size
        try: return s.decode('cp932')
        except: return s.decode('latin1')

r=R(data)
r.raw(11)  # outer magic (11 bytes)
nevents=r.i32()
print("nevents",nevents)

CID_NAMES={102:'Choices',111:'VarCond',112:'StrCond',121:'SetVar',122:'SetStr',
 210:'CommonEvent',211:'CommonEventReserve',300:'CommonEventByName',
 401:'ChoiceCase',402:'SpecialChoiceCase',420:'ElseCase',421:'CancelCase',101:'Message',180:'Wait'}

def read_command(r):
    nargs=r.byte()-1
    cid=r.i32()
    args=[r.i32() for _ in range(nargs)]
    indent=r.byte()
    nstr=r.byte()
    strs=[r.string() for _ in range(nstr)]
    term=r.byte()
    if term==0x01:
        r.raw(5); r.byte(); rc=r.i32()
        for _ in range(rc):
            r.byte(); rn=r.byte(); [r.i32() for _ in range(rn)]; r.raw(2)
    elif term!=0x00:
        raise Exception("bad term %d"%term)
    return (cid,args,indent,strs)

samples=collections.defaultdict(list)
allcmds=[]

# Resync approach: parse events, and within each event parse commands until we
# can't, then scan forward for next 0x8E event header.
pos_after_header=r.i
ev=0
while ev<nevents:
    # find 0x8E
    while r.i<len(data) and data[r.i]!=0x8E:
        r.i+=1
    if r.i>=len(data): break
    r.byte() # 0x8E
    eid=r.i32(); u1=r.i32(); u2=r.raw(7)
    try:
        name=r.string()
        ncmd=r.i32()
        if ncmd<0 or ncmd>200000: raise Exception("bad ncmd")
    except Exception as ex:
        ev+=1; continue
    ev+=1
    for c in range(ncmd):
        try:
            cmd=read_command(r)
        except Exception as ex:
            break
        cid=cmd[0]
        allcmds.append((eid,)+cmd)
        if cid in CID_NAMES and len(samples[cid])<12:
            samples[cid].append((eid,cmd))

print("parsed events approx, total cmds:",len(allcmds))
for cid in [111,112,102,401,421,402,420,210,211,300,121,122]:
    print("\n==== CID %d %s (count=%d) ===="%(cid,CID_NAMES.get(cid,'?'),sum(1 for x in allcmds if x[1]==cid)))
    for eid,(c,args,indent,strs) in samples[cid]:
        print("  ev%-4d args=%s strs=%s"%(eid,args,strs))
