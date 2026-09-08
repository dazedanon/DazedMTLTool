/* Patch 7 (live): resolve the OS window caption from Project\titles.json instead of
 * baking it into the exe. The caption never flows through the db-string reader P5b
 * hooks, so it can't be translated the normal way; this cave reads it straight from
 * the folder at window-creation time.
 *
 *   windowTitle.en non-empty  -> use it
 *   else windowTitle.jp       -> use it
 *   else / no titles.json     -> the engine's own caption (cfg+0x250), i.e. unpatched
 *
 * Nothing game-specific is baked in (works for any SRPG Studio title). Like the other
 * caves, everything it touches comes through the Imp struct the asm stub fills, so the
 * compiled .text has no relocations and runs from any address. Returns a WCHAR* the
 * stub hands back in eax (the hook replaced `mov eax,[eax+250h]`).
 */
typedef unsigned int   u32;
typedef unsigned short u16;
typedef unsigned char  u8;

typedef struct {
    void* (__stdcall *GetProcessHeap)(void);
    void* (__stdcall *HeapAlloc)(void*, u32, u32);
    int   (__stdcall *HeapFree)(void*, u32, void*);
    void* (__stdcall *CreateFileW)(const u16*, u32, u32, void*, u32, u32, void*);
    int   (__stdcall *ReadFile)(void*, void*, u32, u32*, void*);
    int   (__stdcall *CloseHandle)(void*);
    u32   (__stdcall *GetFileSize)(void*, u32*);
    int   (__cdecl   *wsprintfW)(u16*, const u16*, ...);
    int   (__stdcall *MultiByteToWideChar)(u32, u32, const char*, int, u16*, int);
    u32         cfg;            /* *(dword_4E1AF4), the parsed config root */
    const u16*  fmt_path;       /* L"%s\\Project\\titles.json" */
    u16*        outbuf;         /* static UTF-16 buffer in .mtl */
} Imp;

#define INVALID ((void*)-1)
#define OUTMAX  255

/* immediate byte compares only -- no string literals (they would land in .rdata
 * with relocations and break the position-independent splice). */
static __forceinline int is_window(u8* p, u8* e) {   /* "windowTitle" */
    return p + 13 <= e && p[0]=='"' && p[1]=='w' && p[2]=='i' && p[3]=='n' && p[4]=='d'
        && p[5]=='o' && p[6]=='w' && p[7]=='T' && p[8]=='i' && p[9]=='t' && p[10]=='l'
        && p[11]=='e' && p[12]=='"';
}
static __forceinline int is_en(u8* p, u8* e) {       /* "en" */
    return p + 4 <= e && p[0]=='"' && p[1]=='e' && p[2]=='n' && p[3]=='"';
}
static __forceinline int is_jp(u8* p, u8* e) {       /* "jp" */
    return p + 4 <= e && p[0]=='"' && p[1]=='j' && p[2]=='p' && p[3]=='"';
}

/* from just after a key, skip to the opening quote and return the value span. */
static __forceinline void getval(u8* p, u8* lim, u8** vs, u8** ve) {
    while (p < lim && *p != '"') p++;
    if (p >= lim) { *vs = 0; *ve = 0; return; }
    p++;
    u8* s = p;
    while (p < lim) { if (*p == '\\') { p += 2; continue; } if (*p == '"') break; p++; }
    *vs = s; *ve = p;
}
static __forceinline u32 unescape(u8* s, u8* e) {
    u8* w = s; u8* r = s;
    while (r < e) {
        if (*r == '\\' && r + 1 < e) {
            u8 c = r[1]; r += 2;
            if      (c == 'n') *w++ = 0x0A;
            else if (c == 'r') *w++ = 0x0D;
            else if (c == 't') *w++ = 0x09;
            else               *w++ = c;
        } else { *w++ = *r++; }
    }
    return (u32)(w - s);
}

u16* __stdcall resolve_title(Imp* I) {
    u32 cfg = I->cfg;
    u16* orig = *(u16**)(cfg + 0x250);          /* engine's own caption = unpatched */

    u16 path[320];
    I->wsprintfW(path, I->fmt_path, (const u16*)(cfg + 0x8E8));
    void* fh = I->CreateFileW(path, 0x80000000u, 1, 0, 3, 0, 0);
    if (fh == INVALID) return orig;

    u32 sz = I->GetFileSize(fh, 0);
    void* heap = I->GetProcessHeap();
    u8* fb = (u8*)I->HeapAlloc(heap, 0, sz + 1);
    u16* result = orig;
    if (fb) {
        u32 got = 0;
        I->ReadFile(fh, fb, sz, &got, 0);
        u8* e = fb + got;

        u8* w = 0;
        for (u8* p = fb; p + 13 <= e; p++) if (is_window(p, e)) { w = p + 13; break; }
        if (w) {
            u8* ob = w;
            while (ob < e && *ob != '}') ob++;          /* this object's end */
            u8 *ens = 0, *ene = 0, *jps = 0, *jpe = 0;
            for (u8* q = w; q < ob; q++) {
                if (is_en(q, ob)) { getval(q + 4, ob, &ens, &ene); }
                else if (is_jp(q, ob)) { getval(q + 4, ob, &jps, &jpe); }
            }
            u8 *vs = 0, *ve = 0;
            if (ene && ene > ens)      { vs = ens; ve = ene; }   /* en wins if non-empty */
            else if (jpe && jpe > jps) { vs = jps; ve = jpe; }   /* else jp */
            if (vs) {
                u32 m = unescape(vs, ve);
                int wl = I->MultiByteToWideChar(65001, 0, (char*)vs, m, I->outbuf, OUTMAX);
                if (wl > 0) { I->outbuf[wl] = 0; result = I->outbuf; }
            }
        }
        I->HeapFree(heap, 0, fb);
    }
    I->CloseHandle(fh);
    return result;
}
