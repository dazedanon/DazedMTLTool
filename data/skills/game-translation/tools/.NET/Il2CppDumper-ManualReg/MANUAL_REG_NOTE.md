# Il2CppDumper — Manual Registration fork

Fork of Perfare/Il2CppDumper for binaries where the normal auto-search fails (WinLicense / Themida /
Enigma stripped or encrypted the registration; metadata v31+; etc.). Built exe:
`Il2CppDumper/bin/Release/net8.0/Il2CppDumper.exe`.

## Automatic dump mode (preferred — no manual addresses)
Point it at a **flat in-memory dump** (file offset == RVA, e.g. from `Tools\.NET\il2dump`) + the
`global-metadata.dat`, with `ForceManualRegistration: false`. The fork now **auto-detects** a memory
dump (the file spans the whole virtual image), flattens the sections so `MapVATR` works, and searches
the **whole image** with the metadata-anchored search (`MetadataRegistration` = the two
`typeDefinitionsCount` counts; `CodeRegistration` = the `mscorlib.dll`→codeGenModules anchor). This
finds both registrations with **no manual input** even though the stock auto-search fails on the
protected binary (it filters sections by Characteristics, which the protector mangles).
```
Il2CppDumper.exe <in-memory-dump.dll> <global-metadata.dat> <out-dir>
```
Verified on HorizonWalker (metadata v31): auto-found CodeRegistration=0x186493E90,
MetadataRegistration=0x187256420, 261k methods, RVAs disassemble to correct getter/setter code.

The implementation (`PE.EnableDumpModeIfMemoryDump` + whole-image `GetSectionHelper`, wired in
`Program.cs` before `PlusSearch`) reuses the stock anchor search — only the dump detection,
flattening, and unfiltered section ranges are new. Use **manual mode below only if auto fails** (e.g.
the module was ASLR-relocated so the header base ≠ actual base — then pass `ForceManualRegistration`
with the base `il2dump` reported).

## Manual registration mode (fallback)

## When you need it
Stock Il2CppDumper prints `CodeRegistration : 0` / `MetadataRegistration : 0` then dies, AND
Il2CppInspector/Cpp2IL also fail. That means the registration structs aren't statically
locatable. Fix = dump the **decrypted in-memory image**, find the two pointers by hand, and
feed them here.

## Workflow
1. **Get a decrypted in-memory dump** of GameAssembly.dll. Run the game under x64dbg, let the
   protector decrypt (e.g. break at `ntdll.NtTerminateProcess` if it self-exits, or just pause
   after the main menu loads), then dump the module's memory to a flat file (file offset == RVA).
   For >128MB modules dump in chunks and stitch at the right base offset.
2. **Find the two pointers** in the dump (see the skill `il2cpp-game-modding` →
   `reference/il2cpp-dumping.md` for the anchoring technique):
   - MetadataRegistration: anchor on `fieldOffsetsCount == typeDefinitionsSizesCount ==
     typeDefinitionsCount` (two equal counts 6 fields apart), or on the `types` array pointer.
   - CodeRegistration: anchor on `codeGenModules` (count == #images, ptr to an array of module
     ptrs) and back-compute the struct start using the version's field list.
3. **Configure** `config.json` next to the exe:
   ```json
   "ForceManualRegistration": true,
   "ForceCodeRegistration": "<hex VA, no 0x>",
   "ForceMetadataRegistration": "<hex VA, no 0x>",
   "ForceDumpImageBase": "<hex VA, no 0x, e.g. 180000000>",
   "ForceVersion": 31, "RequireAnyKey": false
   ```
4. **Run**: `Il2CppDumper.exe <in-memory-dump.dll> <global-metadata.dat> <out-dir>`
   → `dump.cs` (signatures + RVAs + field offsets), `il2cpp.h`, `script.json`, `DummyDll/`.

## The patch (3 files)
- `Config.cs`: added `ForceManualRegistration`, `ForceCodeRegistration`,
  `ForceMetadataRegistration`, `ForceDumpImageBase`.
- `Program.cs`: when `ForceManualRegistration`, bypass all auto-search → `PE.LoadFromMemory(base)`
  (flattens sections so file-offset == RVA for a dumped image) → `il2Cpp.Init(codeReg, metaReg)`.
- `Il2Cpp.cs`: tolerate null/duplicate type pointers (`typeDic[k]=v`); guard the generic-method
  table block (bounds-checked + try/catch) so an imperfect dump tail doesn't abort the dump.

Build: `dotnet build Il2CppDumper/Il2CppDumper.csproj -c Release -f net8.0`.

---

## Later additions (2026-06)

### Metadata v35 / v38 / v39 support (ported from roytu/Il2CppDumper)
3-way-merged the three version commits (`e19a342` v35, `c462f8b` v38, `bbd9c0c` v39) from
roytu/Il2CppDumper on top of the same Perfare base (`4741d46`), preserving all the fork
customizations below. The metadata version guard is now `version > 39` (was `> 31`). Highlights:
- **v35**: `elementTypeIndex` and string-literal `length` removed (`[Version(Max=31)]`); string length
  inferred from adjacent offsets; enum element type via `parentIndex`; reflection-based
  `Il2CppCodeRegistration.Size(version)`.
- **v38**: variable-length type indices — `ReadTypeIndex` / `ReadTypeDefinitionIndex` /
  `ReadGenericContainerIndex` (1/2/4 bytes by metadata size); `metadata.header.typeDefinitions.offset`.
- **v39**: variable-length `ParameterIndex` (`ReadParameterIndex`); `parameterStart` / parameter default
  value indices become `ParameterIndex`.
All version logic is gated by version, so ≤v31 behavior is unchanged.

### On-disk manual registration (no flattening)
`Program.cs`: in `ForceManualRegistration`, only `LoadFromMemory`/`IsDumped=true` when
`ForceDumpImageBase != 0`. Set `ForceDumpImageBase: "0"` to run manual registration against a normal
**on-disk PE** (keeps correct section mapping). The v38 `ImageBase` computation
(`Version < 38 ? typeDefinitionsOffset : typeDefinitions.offset`) is applied in both the manual and
auto branches.

### Auto-detect legacy 15-field Il2CppCodeRegistration
Some binaries report metadata **v29.1+ (e.g. v31) but ship the older 15-field code-registration**
WITHOUT the `unresolvedInstance/StaticCallPointers` split (seen on **Blue Archive**). `Il2Cpp.Init` now
validates the parsed `codeGenModules` chain (first module name must read as a `*.dll`); if it fails but
the 15-field layout (`Il2CppCodeRegistrationV27NoUnresolvedSplit`) validates, it switches and prints
*"Detected legacy 15-field Il2CppCodeRegistration…"*. **No `Version` change** → normal v29.1+/v31 binaries
are untouched (their chain validates, so this never fires). This replaced an earlier `Max=30` hack that
incorrectly downgraded all v31 dumps. Note: this fixes the *parse*; on an anomalous binary you still need
**manual** CodeRegistration/MetadataRegistration VAs because the auto-search mis-locates the struct start.
