import struct, collections

path = r"C:\Users\sw\Desktop\Wolf\Data\BasicData\CommonEvent.dat"
data = open(path,'rb').read()
class R:
    def __init__(self,b,o=0): self.b=b;self.i=o
    def byte(self): v=self.b[self.i];self.i+=1;return v
    def i32(self): v=struct.unpack_from('<i',self.b,self.i)[0];self.i+=4;return v
    def raw(self,n): v=self.b[self.i:self.i+n];self.i+=n;return v
    def string(self):
        s=self.i32()
        if s<=0 or s>100000: raise Exception("badstr")
        x=self.b[self.i:self.i+s-1];self.i+=s
        return x
r=R(data); r.raw(11); nev=r.i32()
def rc(r):
    n=r.byte()-1; cid=r.i32(); a=[r.i32() for _ in range(n)]; ind=r.byte()
    ns=r.byte(); ss=[r.string() for _ in range(ns)]; t=r.byte()
    if t==0x01:
        r.raw(5);r.byte();k=r.i32()
        for _ in range(k): r.byte();m=r.byte();[r.i32() for _ in range(m)];r.raw(2)
    elif t!=0: raise Exception("term")
    return cid,a,ind,ss
allc=[]
ev=0
while ev<nev:
    while r.i<len(data) and data[r.i]!=0x8E: r.i+=1
    if r.i>=len(data): break
    r.byte(); eid=r.i32(); r.i32(); r.raw(7)
    try:
        r.string(); nc=r.i32()
        if nc<0 or nc>200000: raise Exception()
    except: ev+=1; continue
    ev+=1
    for _ in range(nc):
        try: c=rc(r)
        except: break
        allc.append((eid,)+c)

def U(x):
    return x & 0xFFFFFFFF

# 111 analysis: arg0 high bits, compareOp distribution
print("=== 111 arg0 raw bit analysis ===")
arg0hi=collections.Counter()
cmpops=collections.Counter()
arg0_full=collections.Counter()
for e,cid,a,ind,ss in allc:
    if cid!=111: continue
    a0=U(a[0])
    nbranch=a0 & 0xFF
    arg0_full[a0]+=1
    arg0hi[a0>>8]+=1
    # groups of 3
    for g in range(nbranch):
        if 1+3*g+2 < len(a)+1 and (1+3*g+2)<len(a):
            op=a[1+3*g+2]
            cmpops[op]+=1
print("arg0 distinct values (a0 -> count), showing how high byte varies:")
for v,c in sorted(arg0_full.items())[:40]:
    print("   arg0=%d (0x%X)  lowByte=%d high=0x%X  count=%d"%(v,v,v&0xff,v>>8,c))
print("compareOp distribution:", dict(cmpops))

# Look for samples where arg0 high bits set (AND/OR/else)
print("\n111 samples with arg0 > 7 (flags in high bits):")
seen=0
for e,cid,a,ind,ss in allc:
    if cid!=111: continue
    a0=U(a[0])
    if a0>7:
        print("   ev%d arg0=0x%X args=%s"%(e,a0,a))
        seen+=1
        if seen>=25: break

# 112 analysis
print("\n=== 112 StringCondition ===")
op112=collections.Counter()
a0_112=collections.Counter()
for e,cid,a,ind,ss in allc:
    if cid!=112: continue
    a0_112[U(a[0])]+=1
print("112 arg0 distribution:", dict(sorted(a0_112.items())))
print("112 full samples:")
cnt=0
for e,cid,a,ind,ss in allc:
    if cid!=112: continue
    print("   ev%d args=%s nstr=%d strs=%s"%(e,[U(x) for x in a],len(ss),[s.decode('latin1',errors='replace') for s in ss]))
    cnt+=1
    if cnt>=30: break

# 102 analysis: arg0 bit decode
print("\n=== 102 Choices arg0 decode (nopt vs flags) ===")
for e,cid,a,ind,ss in allc:
    if cid!=102: continue
    a0=U(a[0])
    nopt=len([s for s in ss])
    print("   ev%d arg0=%d (0x%X) bits: b0_3=%d b4=%d b5=%d b6=%d b7=%d b8=%d b9=%d nstrs=%d"%(
        e,a0,a0,a0&0xF,(a0>>4)&1,(a0>>5)&1,(a0>>6)&1,(a0>>7)&1,(a0>>8)&1,(a0>>9)&1,nopt))

# 210/211/300 arg layout
print("\n=== 210 CommonEvent ===")
for e,cid,a,ind,ss in allc:
    if cid==210:
        print("   ev%d args=%s nstr=%d"%(e,[U(x) for x in a],len(ss)))
print("=== 211 CommonEventReserve ===")
for e,cid,a,ind,ss in allc:
    if cid==211:
        print("   ev%d args=%s"%(e,[U(x) for x in a]))
print("=== 300 CommonEventByName (first 15, raw ints) ===")
cnt=0
for e,cid,a,ind,ss in allc:
    if cid==300:
        print("   ev%d args=%s nstr=%d"%(e,[U(x) for x in a],len(ss)))
        cnt+=1
        if cnt>=15: break
