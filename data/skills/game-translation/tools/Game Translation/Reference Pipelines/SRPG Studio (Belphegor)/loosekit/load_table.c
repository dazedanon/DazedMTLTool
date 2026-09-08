/* Patch 5b loose-folder table loader, compiled to position-independent shellcode
 * and spliced into game.exe's .mtl cave. Walks the editable Project\ tree (the
 * native project.dat JSON, with each translatable string wrapped as
 * {"jp": "...", "en": "..."}) and builds the FNV jp->en table the probe reads, so
 * editing a file shows up next launch with no build step and no translation.bin.
 *
 * Everything it touches (Win32 funcs, the base dir, the search keys, the path
 * formats, the g_table global) comes in through the Imp struct the asm stub fills,
 * so the compiled .text has no relocations and runs from any address. The directory
 * walk uses an explicit heap stack (not recursion) so it stays one function.
 */
typedef unsigned int   u32;
typedef unsigned short u16;
typedef unsigned char  u8;

typedef struct {
    void* (__stdcall *HeapAlloc)(void*, u32, u32);
    void* (__stdcall *GetProcessHeap)(void);
    int   (__stdcall *HeapFree)(void*, u32, void*);
    void* (__stdcall *FindFirstFileW)(const u16*, void*);
    int   (__stdcall *FindNextFileW)(void*, void*);
    int   (__stdcall *FindClose)(void*);
    void* (__stdcall *CreateFileW)(const u16*, u32, u32, void*, u32, u32, void*);
    int   (__stdcall *ReadFile)(void*, void*, u32, u32*, void*);
    int   (__stdcall *CloseHandle)(void*);
    u32   (__stdcall *GetFileSize)(void*, u32*);
    int   (__cdecl   *wsprintfW)(u16*, const u16*, ...);
    int   (__stdcall *MultiByteToWideChar)(u32, u32, const char*, int, u16*, int);
    const u16*  base_dir;          /* <gamedir> */
    void**      g_table;
    const u16*  fmt_star;          /* L"%s\\*" */
    const u16*  fmt_child;         /* L"%s\\%s" */
    const char* jpkey;             /* "jp\": \"" */
    const char* enkey;             /* "en\": \"" */
    const u16*  rootname;          /* L"Project" */
} Imp;

#define NB      32768u
#define ARENA   (12u * 1024u * 1024u)
#define INVALID ((void*)-1)
#define SLOTS   256
#define PLEN    300

static __forceinline u32 jhash(const u8* p, u32 n) {
    u32 h = 2166136261u;
    while (n) { h ^= *p++; h *= 16777619u; n--; }
    return h;
}
static __forceinline u8* after(u8* hay, u8* end, const char* key) {
    u32 kl = 0; while (key[kl]) kl++;
    for (u8* q = hay; q + kl <= end; q++) {
        u32 i = 0; while (i < kl && q[i] == (u8)key[i]) i++;
        if (i == kl) return q + kl;
    }
    return 0;
}
static __forceinline u8* vend(u8* v, u8* lim) {
    while (v < lim) {
        if (*v == '\\') { v += 2; continue; }
        if (*v == '"') return v;
        v++;
    }
    return lim;
}
static __forceinline u32 unescape(u8* s, u8* e) {
    u8* w = s; u8* r = s;
    while (r < e) {
        if (*r == '\\' && r + 1 < e) {
            u8 c = r[1]; r += 2;
            if      (c == 'n') *w++ = 0x0A;
            else if (c == 'r') *w++ = 0x0D;
            else if (c == 't') *w++ = 0x09;
            else if (c == 'b') *w++ = 0x08;
            else if (c == 'f') *w++ = 0x0C;
            else               *w++ = c;
        } else {
            *w++ = *r++;
        }
    }
    return (u32)(w - s);
}
static __forceinline int eqb(const u8* a, const u8* b, u32 n) {
    while (n) { if (*a++ != *b++) return 0; n--; }
    return 1;
}
static __forceinline void wcopy(u16* d, const u16* s) {
    int i = 0; while (s[i] && i < PLEN - 1) { d[i] = s[i]; i++; } d[i] = 0;
}

void __stdcall load_table(Imp* I) {
    void* heap = I->GetProcessHeap();
    u8* base = (u8*)I->HeapAlloc(heap, 8 /*HEAP_ZERO_MEMORY*/, 8 + NB * 4 + ARENA);
    if (!base) { *I->g_table = INVALID; return; }
    *(u32*)base = NB;
    u32* buckets = (u32*)(base + 8);
    u32 cursor = 8 + NB * 4, ne = 0;

    u16* stack = (u16*)I->HeapAlloc(heap, 0, SLOTS * PLEN * 2);
    if (!stack) { I->HeapFree(heap, 0, base); *I->g_table = INVALID; return; }
    int sp = 0;
    I->wsprintfW(stack, I->fmt_child, I->base_dir, I->rootname);
    sp = 1;

    u16 cur[PLEN], pat[PLEN], child[PLEN];
    u8 fd[0x250];

    while (sp > 0) {
        sp--;
        wcopy(cur, stack + sp * PLEN);
        I->wsprintfW(pat, I->fmt_star, cur);
        void* h = I->FindFirstFileW(pat, fd);
        if (h == INVALID) continue;
        do {
            u16* name = (u16*)(fd + 0x2C);
            if (name[0] == '.' && (name[1] == 0 || (name[1] == '.' && name[2] == 0)))
                continue;
            I->wsprintfW(child, I->fmt_child, cur, name);
            if (*(u32*)(fd + 0) & 0x10) {                 /* directory */
                if (sp < SLOTS) { wcopy(stack + sp * PLEN, child); sp++; }
                continue;
            }
            int L = 0; while (name[L]) L++;
            if (!(L > 5 && name[L - 5] == '.' && name[L - 4] == 'j' &&
                  name[L - 3] == 's' && name[L - 2] == 'o' && name[L - 1] == 'n'))
                continue;

            void* fh = I->CreateFileW(child, 0x80000000u, 1, 0, 3, 0, 0);
            if (fh == INVALID) continue;
            u32 sz = I->GetFileSize(fh, 0);
            u8* fb = (u8*)I->HeapAlloc(heap, 0, sz + 2);
            if (fb) {
                u32 got = 0;
                I->ReadFile(fh, fb, sz, &got, 0);
                u8* p = fb; u8* e = fb + got;
                for (;;) {
                    u8* js = after(p, e, I->jpkey);   if (!js) break;
                    u8* je = vend(js, e);
                    u8* es = after(je, e, I->enkey);  if (!es) break;
                    u8* ee = vend(es, e);
                    p = ee;
                    u32 em = unescape(es, ee);
                    if (!em || cursor + 0x8000 >= 8 + NB * 4 + ARENA)
                        continue;                          /* blank en -> show JP */
                    u32 off = cursor;
                    u32 jm = unescape(js, je);
                    int jw = I->MultiByteToWideChar(65001, 0, (char*)js, jm, (u16*)(base + off + 4), 8000);
                    *(u16*)(base + off + 4 + jw * 2) = 0;
                    u32 jplen = (u32)(jw + 1) * 2; *(u32*)(base + off) = jplen;
                    u32 eoff = off + 4 + jplen;
                    int ew = I->MultiByteToWideChar(65001, 0, (char*)es, em, (u16*)(base + eoff + 4), 8000);
                    *(u16*)(base + eoff + 4 + ew * 2) = 0;
                    u32 enlen = (u32)(ew + 1) * 2; *(u32*)(base + eoff) = enlen;
                    u32 hh = jhash(base + off + 4, jplen) & (NB - 1);
                    for (;;) {
                        u32 b = buckets[hh];
                        if (!b) { buckets[hh] = off; ne++; cursor = eoff + 4 + enlen; break; }
                        if (*(u32*)(base + b) == jplen && eqb(base + b + 4, base + off + 4, jplen)) break;
                        hh = (hh + 1) & (NB - 1);
                    }
                }
                I->HeapFree(heap, 0, fb);
            }
            I->CloseHandle(fh);
        } while (I->FindNextFileW(h, fd));
        I->FindClose(h);
    }

    I->HeapFree(heap, 0, stack);
    if (ne == 0) { I->HeapFree(heap, 0, base); *I->g_table = INVALID; return; }
    *(u32*)(base + 4) = ne;
    *I->g_table = base;
}
