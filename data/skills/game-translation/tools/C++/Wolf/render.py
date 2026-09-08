def operand(v):
    v &= 0xFFFFFFFF
    if v >= 0x80000000:
        return str(v - 0x100000000)
    if v < 1000000: return str(v)
    if v < 2000000:
        n = v - 1000000
        if 600000 <= n < 600100: return "CSelf[%d]"%(n-600000)
        return "Self[%d]"%n
    if v < 3000000: return "V[%d]"%(v-2000000)
    if v < 4000000: return "S[%d]"%(v-3000000)
    if 9000000 <= v < 10000000: return "Sys[%d]"%(v-9000000)
    return str(v)

CMP={0:'<=',1:'>=',2:'==',3:'!=',4:'<',5:'>',6:'&bitAND'}
def render111(args):
    a0=args[0]&0xFFFFFFFF
    nb=a0 & 0x0F
    mode = 'AND' if (a0 & 0x10) else 'OR'
    parts=[]
    for g in range(nb):
        L=args[1+3*g]; R=args[1+3*g+1]; op=args[1+3*g+2]
        parts.append("%s %s %s"%(operand(L), CMP.get(op,'?op%d'%op), operand(R)))
    joiner = ' && ' if mode=='AND' else ' || '
    return "if (" + joiner.join(parts) + ")"

S=[
 [1, 1600002, 1, 1],
 [3, 1600002, 1, 2, 1600002, 2, 2, 1600002, 3, 2],
 [17, 1600001, 0xFFFFFFFF, 3],
 [18, 1600000, 20, 2, 1600000, 21, 2],
 [2, 1600001, 1, 1, 1600001, 0xFFFFFFFF, 3],
]
print("=== 111 ===")
for s in S: print(" ",s,"->",render111(s))

def render112(args, strs):
    a0=args[0]&0xFFFFFFFF
    nb=a0 & 0x0F
    mode='AND' if (a0&0x10) else 'OR'
    parts=[]
    for g in range(nb):
        L=args[1+g]
        rhs = strs[g] if g < len(strs) else ''
        parts.append('%s == "%s"'%(operand(L), rhs))
    return "if (" + (' && ' if mode=='AND' else ' || ').join(parts)+")"
print("=== 112 ===")
T=[([1,270035465],['a','','','']),([17,1600006],['hi','','','']),([2,270035463,1600007],['x','y','',''])]
for a,ss in T: print(" ",a,ss,"->",render112(a,ss))

def render102(args, strs):
    a0=args[0]&0xFFFFFFFF
    n=a0 & 0x0F
    leftright = bool(a0 & 0x10)
    forced    = bool(a0 & 0x20)
    cancel_no = bool(a0 & 0x40)
    columns   = (a0>>8)&3
    return "ShowChoices n=%d opts=%s [LR=%d forced=%d bit6=%d colHi=%d raw=0x%X]"%(
        n, strs[:n], leftright, forced, cancel_no, columns, a0)
print("=== 102 ===")
C=[([19],['Brace','x','y']),([0x313],['Draw','Pass','x']),([0xBA],['Shoot']+['']*8+['Return']),([67],['Use','Discard','Return'])]
for a,ss in C: print(" 0x%X"%(a[0]),render102(a,ss))

def render300(args, strs):
    name = strs[0] if strs else '?'
    a1=args[1]&0xFFFFFFFF
    nint = a1 & 0xFF
    hi = a1 >> 8
    ints=[operand(args[2+i]) for i in range(nint)]
    return 'CallByName "%s"(intArgs=%s) [arg1=0x%X nint=%d hi=0x%X]'%(name[:8], ints, a1, nint, hi)
print("=== 300 ===")
D=[([0,16777218,1600000,1600001,1600001],['NAME']),([0,2,1600000,1600001],['NM']),([0,1,1600000],['NM']),([0,4,1600011,22,1600002,0],['NM'])]
for a,ss in D: print(" ",render300(a,ss))
