import struct, collections
path=r"C:\Users\sw\Desktop\Wolf\Data\BasicData\CommonEvent.dat"
data=open(path,'rb').read()
class R:
    def __init__(s,b,o=0): s.b=b;s.i=o
    def byte(s): v=s.b[s.i];s.i+=1;return v
    def i32(s): v=struct.unpack_from('<i',s.b,s.i)[0];s.i+=4;return v
    def raw(s,n): v=s.b[s.i:s.i+n];s.i+=n;return v
    def string(s):
        n=s.i32()
        if n<=0 or n>100000: raise Exception()
        x=s.b[s.i:s.i+n-1];s.i+=n;return x
r=R(data);r.raw(11);nev=r.i32()
def rc(r):
    n=r.byte()-1;cid=r.i32();a=[r.i32() for _ in range(n)];ind=r.byte()
    ns=r.byte();ss=[r.string() for _ in range(ns)];t=r.byte()
    if t==1:
        r.raw(5);r.byte();k=r.i32()
        for _ in range(k): r.byte();m=r.byte();[r.i32() for _ in range(m)];r.raw(2)
    elif t!=0: raise Exception()
    return cid,a,ind,ss
allc=[];ev=0
while ev<nev:
    while r.i<len(data) and data[r.i]!=0x8E: r.i+=1
    if r.i>=len(data): break
    r.byte();eid=r.i32();r.i32();r.raw(7)
    try:
        r.string();nc=r.i32()
        if nc<0 or nc>200000: raise Exception()
    except: ev+=1;continue
    ev+=1
    for _ in range(nc):
        try: c=rc(r)
        except: break
        allc.append((eid,c[0],[x&0xffffffff for x in c[1]],c[2],c[3]))
U=lambda x:x&0xffffffff

# Reconstruct nesting: track which 111/102 are followed by 401/420/etc using indent
# Build sequential list to see ChoiceCase indices following Choices
print("=== Choices(102) followed by ChoiceCase(401)/SpecialChoiceCase(402)/CancelCase(421) ===")
seq=[(c[1],c[2],c[3],c[4]) for c in allc]  # cid,args,indent? wait c structure
# allc entries: (eid,cid,args,indent,strs)
# redo
seq=allc
i=0
shown=0
while i<len(seq) and shown<6:
    eid,cid,args,ind,ss=seq[i]
    if cid==102:
        print("\nChoices ev%d arg0=0x%X nopt=%d opts=%s"%(eid,args[0],len(ss),[s.decode('latin1','replace')[:15] for s in ss]))
        # following cases at indent+1
        j=i+1
        while j<len(seq):
            e2,c2,a2,i2,s2=seq[j]
            if c2 in (401,402,420,421) and i2==ind+1:
                nm={401:'Case',402:'SpecialCase',420:'Else',421:'Cancel'}[c2]
                print("    %s arg=%s indent=%d"%(nm,a2,i2))
            elif i2<=ind and c2 not in (401,402,420,421,499):
                break
            j+=1
        shown+=1
    i+=1

# 111 followed by ElseCase
print("\n=== VariableCondition(111) with following ElseCase(420) ===")
shown=0;i=0
while i<len(seq) and shown<8:
    eid,cid,args,ind,ss=seq[i]
    if cid==111 and args[0]>7:
        nb=args[0]&0xF; andflag=(args[0]>>4)&1
        groups=[(args[1+3*g],args[1+3*g+1],args[1+3*g+2]) for g in range(nb)]
        # look ahead for ElseCase at indent+1 before BranchEnd
        haselse=False
        j=i+1;depth=0
        while j<len(seq):
            e2,c2,a2,i2,s2=seq[j]
            if i2==ind+1 and c2==420: haselse=True;break
            if i2<=ind: break
            j+=1
        print("ev%d arg0=0x%X nb=%d AND=%d groups=%s hasElse=%s"%(eid,args[0],nb,andflag,groups,haselse))
        shown+=1
    i+=1

# 121 SetVar nibble decode arg[3]
print("\n=== 121 SetVariable arg[3] operator nibbles ===")
opv=collections.Counter()
for eid,cid,args,ind,ss in seq:
    if cid==121 and len(args)>=4:
        opv[args[3]]+=1
for v,c in sorted(opv.items()):
    print("   arg3=%d (0x%04X) modifyNibble=0x%02X00 binNibble=0x%X000 flags=0x%X count=%d"%(
        v,v,(v>>8)&0xF,(v>>12)&0xF,v&0xFF,c))

# 300 int layout: arg0 always 0? arg1 = self-target id? then ints. show distinct arg0
print("\n=== 300 CommonEventByName arg structure ===")
a0=collections.Counter();lens=collections.Counter()
for eid,cid,args,ind,ss in seq:
    if cid==300:
        a0[args[0]]+=1; lens[len(args)]+=1
print("arg0 dist:",dict(a0))
print("nargs dist:",dict(lens))
cnt=0
for eid,cid,args,ind,ss in seq:
    if cid==300 and cnt<20:
        print("   ev%d args=%s nstr=%d"%(eid,args,len(ss)));cnt+=1
