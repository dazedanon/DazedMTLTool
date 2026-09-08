/* Patch 8: apply loose-folder fontSize edits in-engine, no extra files.
 *
 * fontSize is the one database field that isn't a string, so the P5b text path
 * (which matches Japanese text and swaps it) can't reach it. This cave reads the
 * ten fontSize values straight out of the editable Project\fonts.json and writes
 * them onto the parsed FONTDATA records, so editing fonts.json shows next launch
 * with no rebuild and no loose project.dat -- same edit-and-relaunch promise as
 * the text.
 *
 * Spliced into the font-system builder (sub_402170) at the point it first reads
 * the config; by then the records are parsed. Each FONTDATA node holds its id at
 * +0x08 and its fontSize at +0x20; the list hangs off config+0x1B4. Like the P5b
 * loader, everything it touches comes through the Imp struct the asm stub fills,
 * so the compiled .text has no relocations and runs from any address.
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
    u32         cfg;            /* *(dword_4E1AF4), the parsed config root */
    const u16*  fmt_path;       /* L"%s\\Project\\fonts.json" */
} Imp;

#define INVALID ((void*)-1)

/* No string literals anywhere: the compiler would park them in .rdata and emit
 * relocations, which would break the position-independent splice. The JSON keys
 * are matched with immediate byte compares instead. */
static __forceinline int rdint(u8** pp, u8* e) {
    u8* p = *pp;
    while (p < e && (*p == ' ' || *p == '\t')) p++;
    int n = 0, any = 0;
    while (p < e && *p >= '0' && *p <= '9') { n = n * 10 + (*p - '0'); p++; any = 1; }
    *pp = p;
    return any ? n : -1;
}
static __forceinline int is_id(u8* p, u8* e) {       /* "id": */
    return p + 5 <= e && p[0] == '"' && p[1] == 'i' && p[2] == 'd' && p[3] == '"' && p[4] == ':';
}
static __forceinline int is_size(u8* p, u8* e) {     /* "fontSize": */
    return p + 11 <= e && p[0] == '"' && p[1] == 'f' && p[2] == 'o' && p[3] == 'n' && p[4] == 't'
        && p[5] == 'S' && p[6] == 'i' && p[7] == 'z' && p[8] == 'e' && p[9] == '"' && p[10] == ':';
}

void __stdcall apply_fontsize(Imp* I) {
    u32 cfg = I->cfg;
    if (!cfg) return;

    u16 path[320];
    I->wsprintfW(path, I->fmt_path, (const u16*)(cfg + 0x8E8));
    void* fh = I->CreateFileW(path, 0x80000000u, 1, 0, 3, 0, 0);
    if (fh == INVALID) return;

    u32 sz = I->GetFileSize(fh, 0);
    void* heap = I->GetProcessHeap();
    u8* fb = (u8*)I->HeapAlloc(heap, 0, sz + 1);
    if (fb) {
        u32 got = 0;
        I->ReadFile(fh, fb, sz, &got, 0);

        int table[16];
        for (int i = 0; i < 16; i++) table[i] = -1;
        int cur = -1;
        u8* p = fb; u8* e = fb + got;
        while (p < e) {
            if (is_id(p, e)) {
                p += 5; cur = rdint(&p, e);
            } else if (is_size(p, e)) {
                p += 11; int v = rdint(&p, e);
                if (cur >= 0 && cur < 16 && v > 0) table[cur] = v;
            } else {
                p++;
            }
        }

        u32 sec = *(u32*)(cfg + 0x1B4);          /* FONTDATA section (config+436) */
        if (sec) {
            u32 cont = *(u32*)(sec + 4);
            if (cont) {
                u32 node = *(u32*)(cont + 4);
                int g = 0;
                while (node && g < 64) {
                    u32 id = *(u32*)(node + 8);
                    if (id < 16 && table[id] > 0)
                        *(u32*)(node + 0x20) = (u32)table[id];
                    node = *(u32*)(node + 4);
                    g++;
                }
            }
        }
        I->HeapFree(heap, 0, fb);
    }
    I->CloseHandle(fh);
}
