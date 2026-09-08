/* tts_jp.c -- companion DLL for natuiso.exe
 *
 * Goal: the auto-voice (Open JTalk) reads the on-screen dialogue text. After the
 * English translation that text is English, which makes the synth path hang. We
 * want the synth to speak the ORIGINAL JAPANESE while English stays on screen.
 *
 * Mechanism: inline-hook the synth entry sub_5E6B10 (RVA 0x1E6B10). It is
 *   __thiscall(this=ECX, const char* text = arg_0 at [esp+4] on entry).
 * The function re-reads arg_0 from its stack slot into EDI well AFTER our entry
 * hook, then hands it to text2mecab/mecab. So at entry we:
 *   1. read the text pointer from [esp+4],
 *   2. normalize it (drop all whitespace) into a scratch buffer,
 *   3. bsearch the EN->JP table (tts_jp_table.bin, sorted by normalized EN key),
 *   4. if found, overwrite [esp+4] with a pointer to our persistent JP C-string.
 * The engine then synthesizes Japanese. Display text is untouched.
 *
 * The table is loaded once on DLL attach. Lookups are read-only afterward, so no
 * locking is needed for the swap (a found entry's JP bytes are immutable & owned
 * by us for the process lifetime).
 *
 * Constraint: this DLL touches ONLY the TTS text. It does not read, alter, or
 * interact with any serial/DRM/licensing code.
 */
#include <windows.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>

/* this DLL's own image base, provided by the linker; used to find files next
 * to the DLL without threading hinst through. */
EXTERN_C IMAGE_DOS_HEADER __ImageBase;

/* Built as a pdh.dll PROXY: the game imports 6 PDH functions. We forward each to
 * the renamed real system dll pdh_orig.dll so the game keeps working, while our
 * DllMain installs the TTS hook. (Reliable MSVC forwarder = linker /export, not
 * a .def, which fails LNK2001 here.) */
#pragma comment(linker, "/export:PdhRemoveCounter=pdh_orig.PdhRemoveCounter")
#pragma comment(linker, "/export:PdhCollectQueryData=pdh_orig.PdhCollectQueryData")
#pragma comment(linker, "/export:PdhGetFormattedCounterValue=pdh_orig.PdhGetFormattedCounterValue")
#pragma comment(linker, "/export:PdhEnumObjectItemsA=pdh_orig.PdhEnumObjectItemsA")
#pragma comment(linker, "/export:PdhOpenQueryA=pdh_orig.PdhOpenQueryA")
#pragma comment(linker, "/export:PdhAddCounterA=pdh_orig.PdhAddCounterA")

/* ---- table ----------------------------------------------------------------*/
/* file format (little-endian):
 *   'TTSJ', u32 count, then count records sorted by key bytes:
 *     u32 keylen, key[keylen]   (normalized EN, utf-8, NO trailing nul)
 *     u32 vallen, val[vallen]   (JP, utf-8, NO trailing nul)
 * We index it in memory as arrays of (ptr,len). Values are nul-terminated by us
 * at load (we copy into a single owned blob and append a nul after each value).
 */
typedef struct { const char* k; uint32_t klen; const char* v; /* nul-term */ } Rec;
static Rec*     g_recs  = NULL;
static uint32_t g_count = 0;
static char*    g_blob  = NULL;     /* owns all key+val bytes (+ value nuls)   */
static FILE*    g_log   = NULL;

static void logf_(const char* fmt, ...) {
    if (!g_log) return;
    va_list ap; va_start(ap, fmt); vfprintf(g_log, fmt, ap); va_end(ap);
    fflush(g_log);
}

/* whitespace dropped from keys/lookups: space, tab, CR, LF, and UTF-8 bytes of
 * the full-width space U+3000 (E3 80 80) and NBSP-ish; we drop them byte-wise to
 * match build_tts_table.py which strips the CHARACTERS ' \t\r\n　 '.
 * To keep the C side simple and exactly equivalent, we strip the same chars by
 * decoding the few multibyte ones explicitly. */
static int is_ws_byte_run(const unsigned char* p, int* adv) {
    unsigned char c = p[0];
    if (c == ' ' || c == '\t' || c == '\r' || c == '\n') { *adv = 1; return 1; }
    /* U+3000 IDEOGRAPHIC SPACE = E3 80 80 */
    if (c == 0xE3 && p[1] == 0x80 && p[2] == 0x80) { *adv = 3; return 1; }
    /* U+00A0 NBSP = C2 A0 */
    if (c == 0xC2 && p[1] == 0xA0) { *adv = 2; return 1; }
    *adv = 1; return 0;
}

/* normalize src -> dst (dst must hold >= strlen(src)+1). returns dst length. */
static int normalize(const char* src, char* dst, int cap) {
    int n = 0; const unsigned char* p = (const unsigned char*)src;
    while (*p) {
        int adv;
        if (is_ws_byte_run(p, &adv)) { p += adv; continue; }
        /* copy 'adv' raw bytes (adv==1 for normal bytes) */
        for (int i = 0; i < adv && *p; ++i) {
            if (n < cap - 1) dst[n++] = (char)*p;
            ++p;
        }
    }
    dst[n] = 0;
    return n;
}

static int rec_cmp(const char* k, uint32_t klen, const Rec* r) {
    uint32_t m = klen < r->klen ? klen : r->klen;
    int c = memcmp(k, r->k, m);
    if (c) return c;
    if (klen < r->klen) return -1;
    if (klen > r->klen) return 1;
    return 0;
}

static const char* lookup(const char* normkey, uint32_t klen) {
    int lo = 0, hi = (int)g_count - 1;
    while (lo <= hi) {
        int mid = (lo + hi) >> 1;
        int c = rec_cmp(normkey, klen, &g_recs[mid]);
        if (c == 0) return g_recs[mid].v;
        if (c < 0) hi = mid - 1; else lo = mid + 1;
    }
    return NULL;
}

static int load_table(const char* path) {
    FILE* f = fopen(path, "rb");
    if (!f) { logf_("table open FAIL: %s\n", path); return 0; }
    fseek(f, 0, SEEK_END); long sz = ftell(f); fseek(f, 0, SEEK_SET);
    char* raw = (char*)malloc(sz);
    if (!raw || fread(raw, 1, sz, f) != (size_t)sz) { fclose(f); free(raw); return 0; }
    fclose(f);
    if (sz < 8 || memcmp(raw, "TTSJ", 4) != 0) { free(raw); logf_("bad magic\n"); return 0; }
    uint32_t count; memcpy(&count, raw + 4, 4);
    /* owned blob: copy key bytes + value bytes, appending a nul after each value */
    g_blob = (char*)malloc(sz + count + 16);
    g_recs = (Rec*)malloc(sizeof(Rec) * count);
    if (!g_blob || !g_recs) { free(raw); return 0; }
    const char* p = raw + 8; char* out = g_blob; uint32_t i;
    for (i = 0; i < count; ++i) {
        uint32_t kl; memcpy(&kl, p, 4); p += 4;
        char* kdst = out; memcpy(out, p, kl); out += kl; p += kl;
        uint32_t vl; memcpy(&vl, p, 4); p += 4;
        char* vdst = out; memcpy(out, p, vl); out += vl; p += vl;
        *out++ = 0;                       /* nul-terminate the JP value */
        g_recs[i].k = kdst; g_recs[i].klen = kl; g_recs[i].v = vdst;
    }
    g_count = count; free(raw);
    logf_("table loaded: %u entries\n", g_count);
    return 1;
}

/* ---- inline hook of sub_5E6B10 -------------------------------------------*/
static uint8_t* g_target = NULL;          /* abs addr of sub_5E6B10 in process */
static uint8_t  g_orig[5];                 /* original 5 bytes we overwrote     */
static uint8_t* g_tramp = NULL;            /* orig5 + jmp back (executable)     */

/* called from the naked stub with the address of the on-stack arg_0 slot.
 * If we have a JP swap, writes the JP pointer into *pslot and returns. */
static void __cdecl do_swap(const char** pslot) {
    const char* en = *pslot;
    if (!en || !*en) return;
    char norm[4096];
    int nl = normalize(en, norm, (int)sizeof(norm));
    if (nl <= 0) return;
    const char* jp = lookup(norm, (uint32_t)nl);
    if (jp) { *pslot = jp; logf_("swap: '%.40s' -> JP\n", en); }
    else     logf_("miss: '%.60s'\n", en);
}

/* naked entry replacement: preserve regs, hand &arg_0 to do_swap, then run the
 * relocated original bytes via the trampoline. On entry esp -> retaddr, [esp+4]
 * = arg_0 (the text ptr). We pass &([esp+4]) = esp+4 BEFORE we push anything. */
static __declspec(naked) void hook_entry(void) {
    __asm {
        pushad                      ; pushes 32 bytes
        pushfd                      ; pushes 4 bytes
        ; now: [esp..esp+3]=flags, [esp+4..esp+35]=regs, [esp+36]=retaddr, [esp+40]=arg_0
        lea  eax, [esp + 40]        ; -> &arg_0 (the text-ptr slot the engine re-reads)
        push eax
        call do_swap
        add  esp, 4
        popfd
        popad
        jmp  g_tramp                ; execute relocated original prologue + jmp back
    }
}

static int install_hook(void) {
    HMODULE base = GetModuleHandleA(NULL);     /* natuiso.exe is the main module */
    g_target = (uint8_t*)base + 0x1E6B10;      /* RVA of sub_5E6B10 (imagebase 0x400000) */

    /* trampoline: copy 5 original bytes, then jmp to target+5 */
    g_tramp = (uint8_t*)VirtualAlloc(NULL, 16, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!g_tramp) return 0;
    memcpy(g_orig, g_target, 5);
    memcpy(g_tramp, g_target, 5);
    g_tramp[5] = 0xE9;                          /* jmp rel32 */
    *(int32_t*)(g_tramp + 6) = (int32_t)((g_target + 5) - (g_tramp + 10));

    /* overwrite entry with jmp hook_entry */
    DWORD old;
    VirtualProtect(g_target, 5, PAGE_EXECUTE_READWRITE, &old);
    g_target[0] = 0xE9;
    *(int32_t*)(g_target + 1) = (int32_t)((uint8_t*)hook_entry - (g_target + 5));
    VirtualProtect(g_target, 5, old, &old);
    FlushInstructionCache(GetCurrentProcess(), g_target, 5);
    logf_("hook installed at %p -> %p (tramp %p)\n", g_target, hook_entry, g_tramp);
    return 1;
}

/* ---- DllMain --------------------------------------------------------------*/
static void init(void) {
    char dir[MAX_PATH], path[MAX_PATH];
    /* table + log live next to the DLL */
    GetModuleFileNameA((HMODULE)&__ImageBase, dir, MAX_PATH);
    char* slash = strrchr(dir, '\\'); if (slash) *(slash + 1) = 0; else dir[0] = 0;
    snprintf(path, MAX_PATH, "%stts_jp.log", dir);
    g_log = fopen(path, "w");
    snprintf(path, MAX_PATH, "%stts_jp_table.bin", dir);
    if (!load_table(path)) { logf_("no table; hook NOT installed\n"); return; }
    install_hook();
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID r) {
    (void)h; (void)r;
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(h);
        init();
    }
    return TRUE;
}
