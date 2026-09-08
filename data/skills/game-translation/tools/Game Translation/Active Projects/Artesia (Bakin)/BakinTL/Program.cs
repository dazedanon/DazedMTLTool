using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using Yukar.Common;
using Yukar.Common.Resource;
using Yukar.Common.Rom;

// Read/inject a DESCRAMBLED Bakin project folder using the game's own common.dll,
// so the rom parse is the engine's parse.
//
// Built for Bakin r64268, which is OLDER than the reference pipeline's r73294 and
// differs in ways that matter to every command here:
//
//   * There is no localization feature at all - no [Localizable] attribute, no
//     LocalizeData ExtraChunk, no StringAttr.guid. Which fields hold player text
//     therefore cannot be read off the metadata; `census` measures it instead.
//   * There is no Font rom resource, so text metrics come from GameSettings.gameFont.
//   * ResourceItem.sAttachResource does not exist. Whether ResourceItem.rbr can be
//     loaded headlessly is measured by `probe`, not assumed.
//   * StringAttr has a HashedStringAttr subclass carrying an Adler-32 of the value.
//     Anything that writes a value has to keep that hash consistent.
static class Program
{
    [System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
    static extern bool SetDllDirectory(string path);

    static string sDataDir;

    static int Main(string[] args)
    {
        Console.OutputEncoding = Encoding.UTF8;
        sDataDir = Environment.GetEnvironmentVariable("BAKIN_DATA");
        if (string.IsNullOrEmpty(sDataDir) || !Directory.Exists(sDataDir))
        {
            Console.Error.WriteLine("set BAKIN_DATA to the game's data folder (holding common.dll)");
            return 2;
        }
        sDataDir = Path.GetFullPath(sDataDir);
        SetDllDirectory(sDataDir);
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) =>
        {
            string f = Path.Combine(sDataDir, new AssemblyName(e.Name).Name + ".dll");
            return File.Exists(f) ? Assembly.LoadFrom(f) : null;
        };
        if (args.Length < 2) { Usage(); return 2; }
        string proj = Path.GetFullPath(args[1]);
        try
        {
            switch (args[0])
            {
                case "probe": return Probe(proj);
                case "census": return Census(proj, Arg(args, 2, "census.tsv"));
                case "attrcensus": return AttrCensus(proj, Arg(args, 2, "attrcensus.tsv"));
                case "roundtrip": return RoundTrip(proj);
                case "export": return Export(proj, Arg(args, 2, "."));
                case "layout": return Layout(proj, Arg(args, 2, "layout.tsv"));
                case "effectparams": return EffectParams(proj, Arg(args, 2, "effectparams.tsv"));
                case "resources": return Resources(proj, Arg(args, 2, "resources.tsv"));
                case "inject":
                    if (args.Length < 4) { Usage(); return 2; }
                    return Inject(proj, args[2], args[3]);
                default: Usage(); return 2;
            }
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.ToString());
            return 1;
        }
    }

    static string Arg(string[] a, int i, string dflt) { return a.Length > i ? a[i] : dflt; }

    static void Usage()
    {
        Console.Error.WriteLine("BakinTL probe     <projDir>");
        Console.Error.WriteLine("BakinTL census    <projDir> [out.tsv]     every JP-bearing string field, measured");
        Console.Error.WriteLine("BakinTL attrcensus<projDir> [out.tsv]     script string attrs by (command, slot)");
        Console.Error.WriteLine("BakinTL roundtrip <projDir>               GATE: must be 0 differing");
        Console.Error.WriteLine("BakinTL export    <projDir> <outDir>      units.jsonl + scripts.jsonl");
        Console.Error.WriteLine("BakinTL layout    <projDir> [out.tsv]");
        Console.Error.WriteLine("BakinTL resources <projDir> [out.tsv]");
        Console.Error.WriteLine("BakinTL inject    <projDir> <translated.jsonl> <outDir>");
    }

    // ---------------------------------------------------------------- catalog

    static Catalog LoadCatalog(string proj)
    {
        Catalog.sResourceDir = proj + Path.DirectorySeparatorChar;
        var catalog = new Catalog(false);
        Catalog.sInstance = catalog;
        var files = Directory.GetFiles(proj, "*.rbr", SearchOption.TopDirectoryOnly).ToList();
        string mapDir = Path.Combine(proj, "map");
        if (Directory.Exists(mapDir))
            files.AddRange(Directory.GetFiles(mapDir, "*.rbr", SearchOption.TopDirectoryOnly));
        // GameSettings must land first: everything else resolves against it.
        files = files.OrderBy(f => Path.GetFileName(f).Equals("GameSettings.rbr", StringComparison.OrdinalIgnoreCase) ? 0 : 1)
                     .ToList();
        foreach (var f in files)
            using (var fs = File.OpenRead(f))
                catalog.load(Catalog.FileType.RBR, fs, Catalog.OVERWRITE_RULES.NEVER, true);

        // Folders serialise Childs (resolved objects), not ChildIds (the guids that
        // were loaded); without this the writer emits every folder empty.
        foreach (Folder folder in catalog.getFilteredItemList(typeof(Folder), false))
            folder.initialize(catalog, false);
        var gs = catalog.getGameSettings(false);
        if (gs != null) gs.initCommonEventListInfo(catalog);
        return catalog;
    }

    static int Probe(string proj)
    {
        var catalog = LoadCatalog(proj);
        Console.WriteLine("scripts        : " + catalog.getFilteredItemList(typeof(Script), false).Count);
        Console.WriteLine("maps           : " + catalog.getFilteredItemList(typeof(Map), false).Count);
        Console.WriteLine("events         : " + catalog.getFilteredItemList(typeof(Event), false).Count);
        Console.WriteLine("resourceItems  : " + catalog.getFilteredItemList(typeof(ResourceItem), false).Count);
        Console.WriteLine("gameSettings   : " + (catalog.getGameSettings(false) != null));
        var lp = catalog.getLayoutProperties();
        Console.WriteLine("layoutProps    : " + (lp != null));
        if (lp != null)
        {
            Console.WriteLine("layoutNodes    : " + lp.AllLayoutNodes.Count);
            Console.WriteLine("  system/user  : " + lp.SystemLayoutNodes.Count + " / " + lp.UserLayoutNodes.Count);
        }
        var chunks = catalog.getFilteredItemList(typeof(ExtraChunk), false);
        Console.WriteLine("extraChunks    : " + chunks.Count);
        foreach (ExtraChunk c in chunks)
            Console.WriteLine("   chunk " + c.GetChunkId() + "  " + (c.name ?? ""));
        int hashed = 0, plain = 0;
        foreach (Script s in catalog.getFilteredItemList(typeof(Script), false))
            foreach (var cmd in s.commands)
                foreach (var a in cmd.attrList)
                {
                    if (a is Script.HashedStringAttr) hashed++;
                    else if (a is Script.StringAttr) plain++;
                }
        Console.WriteLine("stringAttrs    : " + plain + " plain / " + hashed + " hashed");
        var gs = catalog.getGameSettings(false);
        if (gs != null) Console.WriteLine("gameFont       : " + (gs.gameFont ?? "(none)"));
        return 0;
    }

    // ---------------------------------------------------------------- census
    //
    // r64268 has no [Localizable] marker, so the set of fields that hold player
    // text is a measurement, not metadata. Walk every reachable object from the
    // catalog roots, and record every string / string[] field whose value contains
    // Japanese, grouped by declaring type and field name. The resulting table is
    // what the export whitelist is built from - reading it is a required step, not
    // an optional report, because a field left off ships untranslated and no
    // per-unit check can ever see it.

    class Bucket
    {
        public int Count;
        public int Chars;
        public List<string> Samples = new List<string>();
    }

    static int Census(string proj, string outPath)
    {
        var catalog = LoadCatalog(proj);
        var buckets = new SortedDictionary<string, Bucket>(StringComparer.Ordinal);
        var seen = new HashSet<object>(ReferenceComparer.Instance);
        var rows = new List<string[]>();

        Action<string, string, string> hit = (path, owner, val) =>
        {
            if (!HasJp(val)) return;
            Bucket b;
            if (!buckets.TryGetValue(path, out b)) buckets[path] = b = new Bucket();
            b.Count++;
            b.Chars += val.Length;
            if (b.Samples.Count < 3) b.Samples.Add(val);
            rows.Add(new string[] { path, owner, val });
        };

        foreach (var rom in catalog.getFilteredItemList(typeof(RomItem), false))
            Walk(rom, rom.GetType().Name, RomLabel(rom), 0, seen, hit);
        var gs = catalog.getGameSettings(false);
        if (gs != null) Walk(gs, "GameSettings", "GameSettings", 0, seen, hit);
        var lp = catalog.getLayoutProperties();
        if (lp != null)
            foreach (var node in lp.AllLayoutNodes)
                Walk(node, "LayoutNode", node.Name ?? "", 0, seen, hit);

        using (var w = new StreamWriter(outPath, false, new UTF8Encoding(false)))
        {
            w.WriteLine("path\towner\tvalue");
            foreach (var r in rows) w.WriteLine(Esc(r[0]) + "\t" + Esc(r[1]) + "\t" + Esc(r[2]));
        }

        Console.WriteLine(string.Format("{0,-58}{1,8}{2,10}   {3}", "field path", "units", "chars", "sample"));
        int total = 0, chars = 0;
        foreach (var kv in buckets.OrderByDescending(x => x.Value.Count))
        {
            Console.WriteLine(string.Format("{0,-58}{1,8}{2,10}   {3}", kv.Key, kv.Value.Count, kv.Value.Chars,
                Trim(kv.Value.Samples.FirstOrDefault() ?? "", 60)));
            total += kv.Value.Count;
            chars += kv.Value.Chars;
        }
        Console.WriteLine(string.Format("{0,-58}{1,8}{2,10}", "TOTAL (" + buckets.Count + " distinct paths)", total, chars));
        Console.WriteLine("-> " + outPath);
        return 0;
    }

    // Bounded reflective walk. Recurses only into Yukar types and into
    // lists/arrays of them, keeps a reference-identity visited set so the object
    // graph's cycles terminate, and caps depth because a Map holds a whole scene.
    const int MAX_DEPTH = 8;

    static void Walk(object o, string typePath, string owner, int depth,
                     HashSet<object> seen, Action<string, string, string> hit)
    {
        if (o == null || depth > MAX_DEPTH) return;
        var t = o.GetType();
        if (!seen.Add(o)) return;

        foreach (var f in t.GetFields(BindingFlags.Public | BindingFlags.Instance))
        {
            object v;
            try { v = f.GetValue(o); } catch { continue; }
            if (v == null) continue;
            string path = typePath + "." + f.Name;
            if (f.FieldType == typeof(string)) { hit(path, owner, (string)v); continue; }
            if (f.FieldType == typeof(string[]))
            {
                var arr = (string[])v;
                for (int i = 0; i < arr.Length; i++) hit(path + "[]", owner, arr[i]);
                continue;
            }
            WalkValue(v, path, owner, depth, seen, hit);
        }
        // Properties are used heavily by LayoutNode, where the fields are private
        // backing stores. Only read parameterless ones and swallow their throws.
        foreach (var p in t.GetProperties(BindingFlags.Public | BindingFlags.Instance))
        {
            if (p.GetIndexParameters().Length != 0 || !p.CanRead) continue;
            if (SKIP_PROPS.Contains(p.Name)) continue;
            object v;
            try { v = p.GetValue(o, null); } catch { continue; }
            if (v == null) continue;
            string path = typePath + "." + p.Name;
            if (p.PropertyType == typeof(string)) { hit(path, owner, (string)v); continue; }
            if (p.PropertyType == typeof(string[]))
            {
                var arr = (string[])v;
                for (int i = 0; i < arr.Length; i++) hit(path + "[]", owner, arr[i]);
                continue;
            }
            WalkValue(v, path, owner, depth, seen, hit);
        }
    }

    static void WalkValue(object v, string path, string owner, int depth,
                          HashSet<object> seen, Action<string, string, string> hit)
    {
        var vt = v.GetType();
        if (vt.IsPrimitive || vt.IsEnum || vt == typeof(Guid) || vt == typeof(DateTime)) return;
        if (IsYukar(vt)) { Walk(v, path, owner, depth + 1, seen, hit); return; }
        var seq = v as IEnumerable;
        if (seq == null || v is string) return;
        if (!seen.Add(v)) return;
        int n = 0;
        foreach (var e in seq)
        {
            if (e == null) continue;
            if (e is string) { hit(path + "[]", owner, (string)e); continue; }
            if (IsYukar(e.GetType())) Walk(e, path + "[]", owner, depth + 1, seen, hit);
            if (++n > 20000) break;
        }
    }

    static bool IsYukar(Type t)
    {
        return t.FullName != null && t.FullName.StartsWith("Yukar.", StringComparison.Ordinal) && !t.IsEnum;
    }

    // Thumbnail materialises a Bitmap per rom; Parent walks back up the tree.
    static readonly HashSet<string> SKIP_PROPS = new HashSet<string> {
        "Thumbnail", "ThumbnailStatus", "Parent", "RefCount", "UseRefCount", "Name" };

    class ReferenceComparer : IEqualityComparer<object>
    {
        public static readonly ReferenceComparer Instance = new ReferenceComparer();
        public new bool Equals(object a, object b) { return ReferenceEquals(a, b); }
        public int GetHashCode(object o) { return System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(o); }
    }

    static string RomLabel(RomItem r)
    {
        return (r.GetType().Name) + ":" + (r.name ?? "") + ":" + r.guId;
    }

    // Which script attribute slots hold player text is the single biggest scoping
    // question on this engine - 92,783 of them contain Japanese and most are engine
    // keys (variable names, switch names, motion names). The answer is a per
    // (command type, attribute index) census, because a slot is display text or a
    // key by its POSITION in a command, never by its content.
    static int AttrCensus(string proj, string outPath)
    {
        var catalog = LoadCatalog(proj);
        var jp = new SortedDictionary<string, Bucket>(StringComparer.Ordinal);
        var all = new SortedDictionary<string, int>(StringComparer.Ordinal);
        var distinct = new Dictionary<string, HashSet<string>>();

        foreach (Script s in catalog.getFilteredItemList(typeof(Script), false))
            foreach (var cmd in s.commands)
                for (int ai = 0; ai < cmd.attrList.Count; ai++)
                {
                    var sa = cmd.attrList[ai] as Script.StringAttr;
                    if (sa == null) continue;
                    string k = cmd.type + "	" + ai;
                    int c; all.TryGetValue(k, out c); all[k] = c + 1;
                    if (!HasJp(sa.value)) continue;
                    Bucket b;
                    if (!jp.TryGetValue(k, out b)) jp[k] = b = new Bucket();
                    b.Count++;
                    b.Chars += sa.value.Length;
                    HashSet<string> d;
                    if (!distinct.TryGetValue(k, out d)) distinct[k] = d = new HashSet<string>(StringComparer.Ordinal);
                    d.Add(sa.value);
                    if (b.Samples.Count < 4 && !b.Samples.Contains(sa.value)) b.Samples.Add(sa.value);
                }

        using (var w = new StreamWriter(outPath, false, new UTF8Encoding(false)))
        {
            w.WriteLine("command	slot	stringAttrs	jpUnits	jpDistinct	jpChars	sample1	sample2	sample3	sample4");
            foreach (var kv in jp.OrderByDescending(x => x.Value.Count))
            {
                var parts = kv.Key.Split('	');
                var b = kv.Value;
                var cells = new List<string> { parts[0], parts[1], all[kv.Key].ToString(),
                    b.Count.ToString(), distinct[kv.Key].Count.ToString(), b.Chars.ToString() };
                for (int i = 0; i < 4; i++) cells.Add(i < b.Samples.Count ? Esc(b.Samples[i]) : "");
                w.WriteLine(string.Join("	", cells));
            }
            // Slots that never hold Japanese still matter: they are the ones an
            // English build could put text into, and they prove a slot was seen.
            foreach (var kv in all)
                if (!jp.ContainsKey(kv.Key))
                {
                    var parts = kv.Key.Split('	');
                    w.WriteLine(string.Join("	", new string[] { parts[0], parts[1],
                        kv.Value.ToString(), "0", "0", "0", "", "", "", "" }));
                }
        }
        Console.WriteLine(string.Format("{0,-34}{1,5}{2,9}{3,9}{4,10}   {5}",
            "command", "slot", "attrs", "jp", "distinct", "sample"));
        int tot = 0;
        foreach (var kv in jp.OrderByDescending(x => x.Value.Count))
        {
            var parts = kv.Key.Split('	');
            Console.WriteLine(string.Format("{0,-34}{1,5}{2,9}{3,9}{4,10}   {5}",
                parts[0], parts[1], all[kv.Key], kv.Value.Count, distinct[kv.Key].Count,
                Trim(kv.Value.Samples.FirstOrDefault() ?? "", 46)));
            tot += kv.Value.Count;
        }
        Console.WriteLine("TOTAL jp-bearing string attrs: " + tot + " over " + jp.Count + " (command, slot) pairs");
        Console.WriteLine("slots with no Japanese at all: " + (all.Count - jp.Count));
        Console.WriteLine("-> " + outPath);
        return 0;
    }

    // ---------------------------------------------------------------- roundtrip

    static int RoundTrip(string proj)
    {
        string outDir = Path.Combine(Path.GetTempPath(), "bakintl_roundtrip");
        if (Directory.Exists(outDir)) Directory.Delete(outDir, true);
        Directory.CreateDirectory(Path.Combine(outDir, "map"));
        var catalog = LoadCatalog(proj);
        // Catalog.clearBackup() probes a "backup" folder next to the CWD.
        Directory.CreateDirectory(Path.Combine(outDir, "backup"));
        Directory.SetCurrentDirectory(outDir);
        int rc = catalog.save(Catalog.FileType.RBR, false, true, false, outDir + Path.DirectorySeparatorChar);
        Console.WriteLine("save rc=" + rc + " -> " + outDir);
        return Compare(proj, outDir);
    }

    static int Compare(string a, string b)
    {
        var names = new SortedSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var d in new[] { a, b })
            foreach (var f in Directory.GetFiles(d, "*.rbr", SearchOption.AllDirectories))
                names.Add(f.Substring(d.Length).TrimStart(Path.DirectorySeparatorChar));
        int same = 0, diff = 0, only = 0;
        foreach (var n in names)
        {
            string fa = Path.Combine(a, n), fb = Path.Combine(b, n);
            if (!File.Exists(fa) || !File.Exists(fb))
            {
                only++;
                Console.WriteLine("ONLY-IN-" + (File.Exists(fa) ? "SRC " : "OUT ") + n);
                continue;
            }
            var x = File.ReadAllBytes(fa);
            var y = File.ReadAllBytes(fb);
            if (x.Length == y.Length && x.SequenceEqual(y)) { same++; continue; }
            diff++;
            int at = 0;
            while (at < x.Length && at < y.Length && x[at] == y[at]) at++;
            Console.WriteLine("DIFF " + n + " src=" + x.Length + " out=" + y.Length + " first@" + at);
        }
        Console.WriteLine("identical " + same + " / differing " + diff + " / one-sided " + only);
        return diff == 0 && only == 0 ? 0 : 1;
    }

    // ---------------------------------------------------------------- export
    //
    // The whitelist below is the OUTPUT of `census` and `attrcensus`, not a
    // guess and not the reference game's. Two measurements decide it:
    //
    //   attrcensus: only 12 (command, slot) pairs in 6,105 scripts hold any
    //   Japanese at all, and one of them - COMMENT slot 0, 508 units - is an
    //   editor comment the engine never draws.
    //
    //   census: 299 distinct string-field paths hold Japanese, and all but the
    //   dozen below are editor names, asset paths, dev-machine import paths or
    //   folder categories. `GfxResourceBase.name` alone is 1,251 units of 3D
    //   model names that are never on screen.
    //
    // Adding a field here costs money; leaving one out ships it untranslated
    // and NO per-unit check can see it, because a string that was never
    // extracted can never fail anything. Re-run both censuses on a new build.

    // (command type, attribute index) -> this slot is display text.
    static readonly Dictionary<string, HashSet<int>> TEXT_SLOTS =
        new Dictionary<string, HashSet<int>>
    {
        { "DIALOGUE",        new HashSet<int> { 0 } },
        { "CHOICES",         new HashSet<int> { 1, 2, 3, 4, 5, 6 } },
        { "MESSAGE",         new HashSet<int> { 0 } },
        { "TELOP",           new HashSet<int> { 0 } },
        { "STRING_VARIABLE", new HashSet<int> { 1 } },
        { "SPTEXT",          new HashSet<int> { 1 } },
        // COMMENT slot 0 is deliberately absent: 508 JP-bearing units, all
        // editor comments, never drawn.
    };

    // Rom type -> the fields on it that are drawn. Everything not listed is an
    // editor name, an asset reference or a formula.
    static readonly Dictionary<string, string[]> ROM_TEXT_FIELDS =
        new Dictionary<string, string[]>
    {
        { "NItem",         new[] { "name", "description", "prefix", "suffix" } },
        { "NSkill",        new[] { "name", "description" } },
        { "Cast",          new[] { "name", "description" } },
        { "Condition",     new[] { "name", "description", "messageForAlly",
                                   "messageForContinue", "messageForEnemy",
                                   "messageForFinished" } },
        { "Attribute",     new[] { "name" } },
        { "Job",           new[] { "name" } },
        { "BattleCommand", new[] { "name" } },
        { "Map",           new[] { "name" } },
        { "Monster",       new[] { "name", "description" } },
        { "Hero",          new[] { "name", "description" } },
        { "Item",          new[] { "name", "description" } },
        { "Skill",         new[] { "name", "description" } },
        // The rom item's own name, which is what the player process puts in
        // the WINDOW TITLE - a different field from `meta.title`, and the two
        // hold the same string here so it is easy to translate one and ship
        // the other. Proven by canary: changing only `meta.title` left the
        // window in Japanese.
        { "GameSettings",  new[] { "name" } },
    };

    // The kind label carried into the store, which is what selects the prompt's
    // per-widget instruction. Keep it stable: it is part of the cache key.
    static string KindFor(string command)
    {
        switch (command)
        {
            case "DIALOGUE": return "text";
            case "CHOICES": return "choice";
            case "MESSAGE": return "message";
            case "TELOP": return "telop";
            case "STRING_VARIABLE": return "strvar";
            case "SPTEXT": return "sptext";
            default: return command.ToLowerInvariant();
        }
    }

    static string RomKind(string type, string field)
    {
        if (type == "GameSettings") return "title";
        if (field == "description") return "desc";
        if (field == "prefix" || field == "suffix") return "affix";
        if (type == "Map") return "mapname";
        if (type == "Condition" && field.StartsWith("messageFor")) return "message";
        return "name";
    }

    static int Export(string proj, string outDir)
    {
        var catalog = LoadCatalog(proj);
        BuildTypeFileMap(proj);
        Directory.CreateDirectory(outDir);

        // Owner and play order for every Script, from all three places a script
        // can live. Without the common-event and battle-event passes, 46,062 of
        // 84,000 dialogue units land in one undifferentiated "(common)" bucket
        // and the scene grouping the model relies on is gone.
        var owner = new Dictionary<Guid, string>();
        var order = new Dictionary<Guid, string>();
        var file = new Dictionary<Guid, string>();

        foreach (Map map in catalog.getFilteredItemList(typeof(Map), false))
        {
            string mapFile = "map/" + (map.name ?? "") + "_" + map.guId + ".rbr";
            int ei = 0;
            foreach (var er in map.getEvents())
            {
                var ev = catalog.getItemFromGuid(er.guId, false) as Event;
                if (ev == null) { ei++; continue; }
                int si = 0;
                foreach (var sheet in ev.sheetList)
                {
                    owner[sheet.script] = "map:" + (map.name ?? "") + " / " + (ev.name ?? "");
                    order[sheet.script] = "1map|" + (map.name ?? "") + "|" + ei.ToString("D4")
                                          + "|" + si.ToString("D3");
                    file[sheet.script] = mapFile;
                    si++;
                }
                ei++;
            }
        }

        var gs = catalog.getGameSettings(true);
        Action<List<Guid>, string, string> commonPass = (list, tag, sortTag) =>
        {
            if (list == null) return;
            for (int i = 0; i < list.Count; i++)
            {
                var ev = catalog.getItemFromGuid(list[i], false) as Event;
                if (ev == null) continue;
                string folder = FolderPath(ev);
                int si = 0;
                foreach (var sheet in ev.sheetList)
                {
                    if (owner.ContainsKey(sheet.script)) { si++; continue; }
                    owner[sheet.script] = tag + ":" + folder + (ev.name ?? "");
                    order[sheet.script] = sortTag + "|" + folder + "|" + i.ToString("D5")
                                          + "|" + si.ToString("D3");
                    file[sheet.script] = "GameSettings.rbr";
                    si++;
                }
            }
        };
        commonPass(gs.commonEvents, "common", "2common");
        commonPass(gs.battleEvents, "battle", "3battle");
        commonPass(gs.sourceEvents, "source", "4source");

        int nCmd = 0;
        using (var w = new StreamWriter(Path.Combine(outDir, "scripts.jsonl"), false, new UTF8Encoding(false)))
        {
            foreach (Script s in catalog.getFilteredItemList(typeof(Script), false))
            {
                var sb = new StringBuilder();
                sb.Append("{\"guid\":").Append(J(s.guId.ToString()))
                  .Append(",\"name\":").Append(J(s.name ?? ""))
                  .Append(",\"owner\":").Append(J(Get(owner, s.guId, "orphan:" + (s.name ?? ""))))
                  .Append(",\"commands\":[");
                for (int ci = 0; ci < s.commands.Count; ci++)
                {
                    var cmd = s.commands[ci];
                    if (ci > 0) sb.Append(',');
                    sb.Append("{\"i\":").Append(ci)
                      .Append(",\"t\":").Append(J(cmd.type.ToString()))
                      .Append(",\"d\":").Append(cmd.indent)
                      .Append(",\"a\":[");
                    for (int ai = 0; ai < cmd.attrList.Count; ai++)
                    {
                        if (ai > 0) sb.Append(',');
                        sb.Append(J(AttrText(cmd.attrList[ai])));
                    }
                    sb.Append("]}");
                    nCmd++;
                }
                sb.Append("]}");
                w.WriteLine(sb.ToString());
            }
        }

        int n = 0, orphan = 0;
        var kinds = new SortedDictionary<string, int>(StringComparer.Ordinal);
        // JSONL, not TSV: the engine's own escapes live inside these strings and a
        // second escaping layer of our own would be ambiguous with them.
        using (var w = new StreamWriter(Path.Combine(outDir, "units.jsonl"), false, new UTF8Encoding(false)))
        {
            Action<string, string, string, string, string, string, string> emit =
                (key, kind, own, ctx, ord, fil, val) =>
            {
                if (!HasJp(val)) return;
                w.WriteLine("{\"key\":" + J(key) + ",\"kind\":" + J(kind)
                            + ",\"owner\":" + J(own) + ",\"ctx\":" + J(ctx)
                            + ",\"order\":" + J(ord) + ",\"file\":" + J(fil)
                            + ",\"src\":" + J(val) + "}");
                int c; kinds.TryGetValue(kind, out c); kinds[kind] = c + 1;
                n++;
            };

            foreach (Script s in catalog.getFilteredItemList(typeof(Script), false))
            {
                string own = Get(owner, s.guId, null);
                if (own == null) { own = "orphan:" + (s.name ?? ""); orphan++; }
                string ord = Get(order, s.guId, "5orphan|" + (s.name ?? "") + "|00000|000");
                string fil = Get(file, s.guId, "GameSettings.rbr");
                for (int ci = 0; ci < s.commands.Count; ci++)
                {
                    var cmd = s.commands[ci];
                    HashSet<int> slots;
                    if (!TEXT_SLOTS.TryGetValue(cmd.type.ToString(), out slots)) continue;
                    for (int ai = 0; ai < cmd.attrList.Count; ai++)
                    {
                        if (!slots.Contains(ai)) continue;
                        var sa = cmd.attrList[ai] as Script.StringAttr;
                        if (sa == null) continue;
                        emit("S:" + s.guId + ":" + ci + ":" + ai, KindFor(cmd.type.ToString()),
                             own, (s.name ?? "") + "#" + ci + "." + ai,
                             ord + "|" + ci.ToString("D5") + "|" + ai, fil, sa.value);
                    }
                }
            }

            // Keyed by (node, position), never by MenuItem.guid: duplicating a
            // layout in the editor clones the item guids too.
            foreach (var node in LayoutNodes(catalog))
            {
                int mi_i = 0;
                foreach (var mi in node.MenuSettings.ParseAllItems())
                {
                    emit("M:" + node.Guid + ":" + mi_i + ":text", "ui",
                         "layout:" + (node.Name ?? ""),
                         mi.itemType + " '" + (mi.name ?? "") + "'",
                         "6ui|" + (node.Name ?? "") + "|" + mi_i.ToString("D4") + "|0",
                         "Layout.rbr", mi.text);
                    mi_i++;
                }
            }

            foreach (var rom in catalog.getFilteredItemList(typeof(RomItem), false))
            {
                string tn = rom.GetType().Name;
                string[] fields;
                if (!ROM_TEXT_FIELDS.TryGetValue(tn, out fields)) continue;
                foreach (var f in fields)
                {
                    string v = GetField(rom, f);
                    if (v == null) continue;
                    emit("R:" + rom.guId + ":" + f, RomKind(tn, f), "db:" + tn,
                         tn + "." + f + " '" + (rom.name ?? "") + "'",
                         "7db|" + tn + "|" + (rom.name ?? "") + "|" + f,
                         RomFile(catalog, rom), v);
                }
            }

            var gl = gs.glossary;
            foreach (var f in gl.GetType().GetFields(BindingFlags.Public | BindingFlags.Instance))
            {
                if (f.FieldType == typeof(string))
                    emit("G:" + f.Name, "term", "glossary", "GameSettings.glossary." + f.Name,
                         "8glossary|" + f.Name + "|0|0", "GameSettings.rbr", (string)f.GetValue(gl));
                else if (f.FieldType == typeof(string[]))
                {
                    var arr = (string[])f.GetValue(gl);
                    if (arr == null) continue;
                    for (int i = 0; i < arr.Length; i++)
                        emit("G:" + f.Name + ":" + i, "term", "glossary",
                             "GameSettings.glossary." + f.Name + "[" + i + "]",
                             "8glossary|" + f.Name + "|" + i.ToString("D3") + "|0",
                             "GameSettings.rbr", arr[i]);
                }
            }

            foreach (var f in new[] { "title", "subTitle", "description", "creator", "license" })
                emit("T:" + f, f == "creator" || f == "license" ? "name" : "title",
                     "meta", "GameSettings.meta." + f, "9meta|" + f + "|0|0",
                     "GameSettings.rbr", GetField(gs.meta, f));
        }
        Console.WriteLine("commands " + nCmd + " / units " + n + " -> " + outDir);
        if (orphan > 0)
            Console.WriteLine("scripts with no owning event: " + orphan
                              + " (their units are still exported, under owner 'orphan:')");
        foreach (var kv in kinds.OrderByDescending(x => x.Value))
            Console.WriteLine(string.Format("   {0,-42}{1,7}", kv.Key, kv.Value));
        return 0;
    }

    // Which rom FILE a database row lands in.
    //
    // Two obvious answers are both wrong. The type NAME is wrong because
    // `BattleCommand` rows serialise into `Cast.rbr` and no `BattleCommand.rbr`
    // exists anywhere - and the injector's copy-through keys its "do not
    // restore" set on this string, so 862 translations were protected only
    // incidentally by the Cast units that named the real file. And the
    // engine's own `Catalog.getRomFileName` is wrong too: it answers
    // "BattleCommand.rbr" for the same type.
    //
    // So it is MEASURED from the tree that is actually on disk: read the
    // record signature of every rom in every top-level .rbr, and map
    // signature -> file. `Catalog.romSignatureToTypeDic` gives type ->
    // signature. A file that is not there cannot be mis-named.
    static Dictionary<Type, string> sTypeFile;

    static void BuildTypeFileMap(string proj)
    {
        sTypeFile = new Dictionary<Type, string>();
        var sigType = (System.Collections.IDictionary)typeof(Catalog).GetField(
            "romSignatureToTypeDic",
            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static)
            .GetValue(null);
        var bySig = new Dictionary<short, Type>();
        if (sigType != null)
            foreach (System.Collections.DictionaryEntry e in sigType)
                bySig[Convert.ToInt16(e.Key)] = (Type)e.Value;

        foreach (var path in Directory.GetFiles(proj, "*.rbr", SearchOption.TopDirectoryOnly))
        {
            byte[] b = File.ReadAllBytes(path);
            if (b.Length < 5 || Encoding.ASCII.GetString(b, 0, 5) != "YUKAR") continue;
            string name = Path.GetFileName(path);
            int p = 5;
            while (p + 6 <= b.Length)
            {
                int len = BitConverter.ToInt32(b, p);
                short sig = BitConverter.ToInt16(b, p + 4);
                if (len < 0 || p + 6 + len > b.Length) break;
                Type t;
                // First file wins: a rom type lives in exactly one file, and a
                // later file merely re-declaring the system record must not
                // move it.
                if (bySig.TryGetValue(sig, out t) && t != null && !sTypeFile.ContainsKey(t))
                    sTypeFile[t] = name;
                p += 6 + len;
            }
        }
    }

    static string RomFile(Catalog catalog, RomItem rom)
    {
        if (rom is Map) return "map/" + (rom.name ?? "") + "_" + rom.guId + ".rbr";
        string f;
        if (sTypeFile != null && sTypeFile.TryGetValue(rom.GetType(), out f)) return f;
        return rom.GetType().Name + ".rbr";
    }

    static string Get(Dictionary<Guid, string> d, Guid k, string dflt)
    {
        string v;
        return d.TryGetValue(k, out v) ? v : dflt;
    }

    static string FolderPath(RomItem r)
    {
        var parts = new List<string>();
        var f = r.Parent;
        int guard = 0;
        while (f != null && guard++ < 16)
        {
            if (!string.IsNullOrEmpty(f.name)) parts.Insert(0, f.name);
            f = f.Parent;
        }
        return parts.Count == 0 ? "" : string.Join("/", parts) + "/";
    }

    // ---------------------------------------------------------------- inject

    static int Inject(string proj, string tlPath, string outDir)
    {
        var tl = new Dictionary<string, string>();
        foreach (var line in File.ReadLines(tlPath, Encoding.UTF8))
        {
            if (line.Trim().Length == 0) continue;
            string key = JField(line, "key"), en = JField(line, "en");
            if (key != null && en != null && en.Length > 0) tl[key] = en;
        }
        Console.WriteLine("translations loaded: " + tl.Count);
        if (tl.Count == 0) { Console.Error.WriteLine("refusing to write an empty translation set"); return 1; }

        var catalog = LoadCatalog(proj);
        var scripts = new Dictionary<Guid, Script>();
        foreach (Script s in catalog.getFilteredItemList(typeof(Script), false)) scripts[s.guId] = s;
        var menuItems = new Dictionary<string, MenuSettings.MenuItem>();
        foreach (var node in LayoutNodes(catalog))
        {
            int mi_i = 0;
            foreach (var mi in node.MenuSettings.ParseAllItems())
                menuItems[node.Guid + ":" + mi_i++] = mi;
        }
        var glossary = catalog.getGameSettings(true).glossary;

        int applied = 0, rehashed = 0;
        var unmatched = new List<string>();
        foreach (var kv in tl)
        {
            var p = kv.Key.Split(':');
            bool ok = false;
            if (p[0] == "S" && p.Length == 4)
            {
                Script s;
                int ci = int.Parse(p[2]), ai = int.Parse(p[3]);
                if (scripts.TryGetValue(new Guid(p[1]), out s) && ci < s.commands.Count
                    && ai < s.commands[ci].attrList.Count)
                {
                    var sa = s.commands[ci].attrList[ai] as Script.StringAttr;
                    if (sa != null)
                    {
                        sa.value = kv.Value;
                        // HashedStringAttr carries an Adler-32 of the value; leaving a
                        // stale hash behind is a silent corruption the round trip
                        // cannot see, because the bytes still parse.
                        var hs = sa as Script.HashedStringAttr;
                        if (hs != null) { hs.hash = hs.GetHash(); rehashed++; }
                        ok = true;
                    }
                }
            }
            else if (p[0] == "M" && p.Length == 4)
            {
                MenuSettings.MenuItem mi;
                if (menuItems.TryGetValue(p[1] + ":" + p[2], out mi)) ok = SetField(mi, p[3], kv.Value);
            }
            else if (p[0] == "R" && p.Length == 3)
            {
                var rom = catalog.getItemFromGuid(new Guid(p[1]), false);
                if (rom != null) ok = SetField(rom, p[2], kv.Value);
            }
            else if (p[0] == "G" && p.Length == 2)
            {
                ok = SetField(glossary, p[1], kv.Value);
            }
            else if (p[0] == "G" && p.Length == 3)
            {
                var f = glossary.GetType().GetField(p[1]);
                if (f != null && f.FieldType == typeof(string[]))
                {
                    var arr = (string[])f.GetValue(glossary);
                    int i = int.Parse(p[2]);
                    if (arr != null && i < arr.Length) { arr[i] = kv.Value; ok = true; }
                }
            }
            else if (p[0] == "T" && p.Length == 2)
            {
                ok = SetField(catalog.getGameSettings(true).meta, p[1], kv.Value);
            }
            if (ok) applied++; else unmatched.Add(kv.Key);
        }
        Console.WriteLine("applied " + applied + " / unmatched " + unmatched.Count + " / rehashed " + rehashed);
        foreach (var u in unmatched.Take(10)) Console.WriteLine("  unmatched " + u);
        if (unmatched.Count > 0 && applied < tl.Count / 2)
        {
            Console.Error.WriteLine("refusing to write: more than half the keys did not resolve");
            return 1;
        }

        if (Directory.Exists(outDir)) Directory.Delete(outDir, true);
        Directory.CreateDirectory(Path.Combine(outDir, "map"));
        Directory.CreateDirectory(Path.Combine(outDir, "backup"));
        Directory.SetCurrentDirectory(outDir);
        int rc = catalog.save(Catalog.FileType.RBR, false, true, false, outDir + Path.DirectorySeparatorChar);
        string bk = Path.Combine(outDir, "backup");
        if (Directory.Exists(bk)) Directory.Delete(bk, true);
        Console.WriteLine("save rc=" + rc + " -> " + outDir);
        Compare(proj, outDir);
        return rc;
    }

    // ---------------------------------------------------------------- layout

    // Every determinant of whether a translation overflows is layout DATA on the
    // MenuItem, so the regime is measured per widget:
    //   useMultiLineText -> the engine word-wraps to size.X (width becomes soft)
    //   useClipping      -> text past size.X is CUT, not merely overlapping
    //   sizeType=AUTO    -> the widget grows to its content and hits its neighbour
    //
    // size.X ALONE IS NOT THE BOUND, and dumping only size.X is what let a whole
    // menu ship with labels sitting outside their plates while the validator
    // reported zero overflows. Two more fields decide it:
    //
    //   image   a background Guid. A label drawn on a decorative plate is bounded
    //           by the PICTURE, whose width no numeric attribute mentions - it has
    //           to be resolved through the resource table and measured off the PNG.
    //           A 256px box over a 180px plate has 76px of room that does not exist.
    //   pos / offset / origin / posType
    //           where the widget actually sits. Without them the distance to the
    //           NEIGHBOUR cannot be computed, so a widget with useClipping=0 - which
    //           collides rather than clipping - has no measurable budget at all.
    static int Layout(string proj, string outPath)
    {
        var catalog = LoadCatalog(proj);
        int rows = 0;
        using (var w = new StreamWriter(outPath, false, new UTF8Encoding(false)))
        {
            w.WriteLine(string.Join("\t", new string[] { "nodeGuid", "node", "usage", "nodeType", "idx", "itemType", "name",
                "sizeType", "sizeX", "sizeY", "scaleX", "textScale", "wordWrap", "clipping", "autoResize",
                "maxLineNum", "lineOffset",
                "posX", "posY", "offsetX", "offsetY", "origin", "posType", "image", "useText",
                "subW", "subH", "subMargin", "subBg", "windowImg", "parent", "layoutType",
                "text" }));
            foreach (var node in LayoutNodes(catalog))
            {
                var ms = node.MenuSettings;
                // ParseAllItems FLATTENS the tree, and a flat dump cannot answer
                // "where is this label actually drawn", because a TEXT_PANEL's
                // position is its own pos plus every ancestor's. Rebuild the
                // parent link by walking items/subItems in the same order and
                // matching object identity - not by re-deriving the order, which
                // would silently drift if ParseAllItems ever changed.
                var flat = ms.ParseAllItems().ToList();
                var indexOf = new Dictionary<MenuSettings.MenuItem, int>();
                for (int k = 0; k < flat.Count; k++)
                    if (!indexOf.ContainsKey(flat[k])) indexOf[flat[k]] = k;
                var parentOf = new Dictionary<int, int>();
                foreach (var mi0 in flat)
                {
                    int pi;
                    if (!indexOf.TryGetValue(mi0, out pi) || mi0.subItems == null) continue;
                    foreach (var kid in mi0.subItems)
                    {
                        int ki;
                        if (indexOf.TryGetValue(kid, out ki)) parentOf[ki] = pi;
                    }
                }
                int i = 0;
                foreach (var mi in ms.ParseAllItems())
                {
                    w.WriteLine(string.Join("\t", new string[] {
                        node.Guid.ToString(), Esc(node.Name ?? ""),
                        node.Usage.ToString(), node.NodeType.ToString(),
                        i.ToString(), mi.itemType.ToString(),
                        Esc(mi.name ?? ""),
                        mi.sizeType.ToString(),
                        mi.size.X.ToString("0.##"), mi.size.Y.ToString("0.##"),
                        mi.scale.X.ToString("0.###"), mi.textScale.ToString("0.###"),
                        mi.useMultiLineText ? "1" : "0",
                        mi.useClipping ? "1" : "0",
                        mi.autoResize ? "1" : "0",
                        node.MaxLineNum.ToString(), node.LineOffset.ToString(),
                        mi.pos.X.ToString("0.##"), mi.pos.Y.ToString("0.##"),
                        mi.offset.X.ToString("0.##"), mi.offset.Y.ToString("0.##"),
                        mi.origin.ToString(), mi.posType.ToString(),
                        mi.image == Guid.Empty ? "" : mi.image.ToString(),
                        mi.useText ? "1" : "0",
                        mi.subItemsBaseWidth.ToString("0.##"),
                        mi.subItemsBaseHeight.ToString("0.##"),
                        mi.subItemMergin.Y.ToString("0.##"),
                        mi.subItemBaseBackground == Guid.Empty ? "" : mi.subItemBaseBackground.ToString(),
                        mi.window == Guid.Empty ? "" : mi.window.ToString(),
                        parentOf.ContainsKey(i) ? parentOf[i].ToString() : "-1",
                        mi.layoutType.ToString(),
                        Esc(mi.text ?? "") }));
                    i++; rows++;
                }
            }
        }
        Console.WriteLine("layout rows " + rows + " -> " + outPath);
        return 0;
    }

    static int Resources(string proj, string outPath)
    {
        var catalog = LoadCatalog(proj);
        var byType = new SortedDictionary<string, int>(StringComparer.Ordinal);
        using (var w = new StreamWriter(outPath, false, new UTF8Encoding(false)))
        {
            w.WriteLine("guid\ttype\tname\tpath");
            foreach (ResourceItem r in catalog.getFilteredItemList(typeof(ResourceItem), false))
            {
                string t = r.GetType().Name;
                int c; byType.TryGetValue(t, out c); byType[t] = c + 1;
                w.WriteLine(string.Join("\t", new string[] {
                    r.guId.ToString(), t, Esc(r.name ?? ""), Esc(r.path ?? "") }));
            }
        }
        foreach (var kv in byType) Console.WriteLine(kv.Key.PadRight(28) + kv.Value);
        return 0;
    }

    // ---------------------------------------------------------------- helpers

    static List<LayoutProperties.LayoutNode> LayoutNodes(Catalog c)
    {
        var lp = c.getLayoutProperties();
        return lp == null ? new List<LayoutProperties.LayoutNode>() : lp.AllLayoutNodes;
    }


    static string AttrText(Script.Attr a)
    {
        var sa = a as Script.StringAttr;
        if (sa != null) return "s:" + sa.value;
        var ia = a as Script.IntAttr;
        if (ia != null) return "i:" + ia.GetInt();
        var fa = a as Script.FloatAttr;
        if (fa != null) return "f:" + fa.GetFloat();
        var ga = a as Script.GuidAttr;
        if (ga != null) return "g:" + ga.GetGuid();
        try { return a.GetType().Name + ":" + (a.GetValue() ?? ""); }
        catch (NotImplementedException) { return a.GetType().Name; }
    }

    // ------------------------------------------------- nested effect params
    //
    // A Condition carries its battle messages TWICE: the flat `messageForAlly`
    // family, and again inside `EffectParamSettings.EffectParamList[]`, where a
    // `ChangeStringParamEffectParamBase` element holds the same string. The
    // ENGINE reads the nested copy, so translating only the flat one leaves the
    // Japanese on screen - "Artesia は麻痺してしまった！" - while every unit in the
    // store is translated and every check is green.
    //
    // ROM_TEXT_FIELDS cannot reach it: that table is flat field names, and this
    // is a settable PROPERTY on an element of a list behind a property. So the
    // list is dumped with its INDEX, which is what makes a write address
    // possible at all.
    static int EffectParams(string proj, string outPath)
    {
        var catalog = LoadCatalog(proj);
        int rows = 0;
        using (var w = new StreamWriter(outPath, false, new UTF8Encoding(false)))
        {
            w.WriteLine(string.Join("\t", new string[] {
                "guid", "type", "owner", "index", "member", "value" }));
            foreach (var rom in catalog.getFilteredItemList(typeof(RomItem), false))
            {
                var sp = rom.GetType().GetProperty("EffectParamSettings");
                if (sp == null) continue;
                object settings = null;
                try { settings = sp.GetValue(rom, null); } catch { continue; }
                if (settings == null) continue;
                var lp = settings.GetType().GetProperty("EffectParamList");
                if (lp == null) continue;
                var list = lp.GetValue(settings, null) as System.Collections.IEnumerable;
                if (list == null) continue;
                int i = 0;
                foreach (var el in list)
                {
                    if (el != null)
                        foreach (var p in el.GetType().GetProperties(
                                     BindingFlags.Public | BindingFlags.Instance))
                        {
                            if (p.PropertyType != typeof(string)) continue;
                            if (!p.CanRead || !p.CanWrite) continue;
                            if (p.GetIndexParameters().Length != 0) continue;
                            string v = null;
                            try { v = (string)p.GetValue(el, null); } catch { continue; }
                            if (string.IsNullOrEmpty(v)) continue;
                            w.WriteLine(string.Join("\t", new string[] {
                                rom.guId.ToString(), rom.GetType().Name,
                                Esc(RomLabel(rom)), i.ToString(), p.Name, Esc(v) }));
                            rows++;
                        }
                    i++;
                }
            }
        }
        Console.WriteLine("effect param strings " + rows + " -> " + outPath);
        return 0;
    }

    // Walk `EffectParamSettings.EffectParamList[3].ChangeParam` and hand back the
    // object that owns the last segment. Returns null if any hop is missing, so a
    // stale index can never write into the wrong element.
    static object ResolvePath(object o, string[] parts, int upto)
    {
        for (int i = 0; i < upto && o != null; i++)
        {
            string seg = parts[i];
            int br = seg.IndexOf('[');
            string nm = br < 0 ? seg : seg.Substring(0, br);
            var pi = o.GetType().GetProperty(nm);
            object next = null;
            if (pi != null) { try { next = pi.GetValue(o, null); } catch { return null; } }
            else
            {
                var fi = o.GetType().GetField(nm);
                if (fi == null) return null;
                try { next = fi.GetValue(o); } catch { return null; }
            }
            if (br >= 0 && next != null)
            {
                int idx;
                string num = seg.Substring(br + 1).TrimEnd(']');
                if (!int.TryParse(num, out idx)) return null;
                var en = next as System.Collections.IEnumerable;
                if (en == null) return null;
                object found = null;
                int k = 0;
                foreach (var e in en) { if (k++ == idx) { found = e; break; } }
                next = found;
            }
            o = next;
        }
        return o;
    }

    static bool SetField(object o, string name, string value)
    {
        if (o == null) return false;
        // A DOTTED path addresses something nested - see `EffectParams`.
        if (name.IndexOf('.') >= 0)
        {
            var parts = name.Split('.');
            object holder = ResolvePath(o, parts, parts.Length - 1);
            if (holder == null) return false;
            string last = parts[parts.Length - 1];
            var pi = holder.GetType().GetProperty(last);
            if (pi != null && pi.PropertyType == typeof(string) && pi.CanWrite)
            {
                pi.SetValue(holder, value, null);
                return true;
            }
            var fi = holder.GetType().GetField(last);
            if (fi != null && fi.FieldType == typeof(string))
            {
                fi.SetValue(holder, value);
                return true;
            }
            return false;
        }
        // A LAYOUT POSITION is the one NON-string field this tool writes, and it
        // has to be writable because several of this game's labels are hand
        // positioned: the author nudged each one so the JAPANESE sits centred on
        // its plate, and a shorter or longer English string drawn at the same x
        // is visibly off centre while every width check still passes.
        //
        // `MenuItem.pos` is a Microsoft.Xna.Framework.Vector2 STRUCT, so
        // GetValue hands back a boxed copy - mutate the box, then write it back,
        // or the assignment is silently lost.
        //
        // Everything else stays string-only on purpose. A generic numeric setter
        // would let one mistyped key rewrite a size, an offset or a colour with
        // nothing to catch it.
        if (name == "posX" || name == "posY" || name == "scaleX" || name == "scaleY")
        {
            // `scale` is the ONLY per-widget font size on this engine: there is
            // no Font resource and no size field, and TextRenderer draws a 72px
            // face at `scale.X * 0.33333334f`. So writing scale.X is how a label
            // is made to fit its plate vertically - the author already does it
            // by hand on the two menu buttons whose Japanese was longest.
            bool isPos = name[0] == 'p';
            var pf = o.GetType().GetField(isPos ? "pos" : "scale");
            if (pf == null || pf.FieldType.Name != "Vector2") return false;
            float v;
            if (!float.TryParse(value, System.Globalization.NumberStyles.Float,
                                System.Globalization.CultureInfo.InvariantCulture, out v))
                return false;
            if (!isPos && (v <= 0f || v > 8f)) return false;   // a scale of 0 erases the text
            object vec = pf.GetValue(o);
            var comp = vec.GetType().GetField(name.EndsWith("X") ? "X" : "Y");
            if (comp == null) return false;
            comp.SetValue(vec, v);
            pf.SetValue(o, vec);
            return true;
        }
        var f = o.GetType().GetField(name);
        if (f == null || f.FieldType != typeof(string)) return false;
        f.SetValue(o, value);
        return true;
    }

    static string GetField(object o, string name)
    {
        if (o == null) return null;
        var f = o.GetType().GetField(name);
        if (f == null || f.FieldType != typeof(string)) return null;
        return (string)f.GetValue(o);
    }

    // Small hand-rolled reader for the flat {"key":...,"en":...} lines we emit.
    static string JField(string line, string name)
    {
        int i = line.IndexOf("\"" + name + "\":");
        if (i < 0) return null;
        i = line.IndexOf('"', i + name.Length + 3);
        if (i < 0) return null;
        var sb = new StringBuilder();
        for (int p = i + 1; p < line.Length; p++)
        {
            char c = line[p];
            if (c == '"') return sb.ToString();
            if (c != '\\') { sb.Append(c); continue; }
            char e = line[++p];
            if (e == 'n') sb.Append('\n');
            else if (e == 'r') sb.Append('\r');
            else if (e == 't') sb.Append('\t');
            else if (e == 'u') { sb.Append((char)Convert.ToInt32(line.Substring(p + 1, 4), 16)); p += 4; }
            else sb.Append(e);
        }
        return null;
    }

    static string J(string s)
    {
        if (s == null) return "\"\"";
        var sb = new StringBuilder("\"");
        foreach (char c in s)
        {
            if (c == '"' || c == '\\') sb.Append('\\').Append(c);
            else if (c == '\n') sb.Append("\\n");
            else if (c == '\r') sb.Append("\\r");
            else if (c == '\t') sb.Append("\\t");
            else if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
            else sb.Append(c);
        }
        return sb.Append('"').ToString();
    }

    static string Esc(string s)
    {
        if (s == null) return "";
        return s.Replace("\\", "\\\\").Replace("\t", "\\t").Replace("\r", "\\r").Replace("\n", "\\n");
    }

    static string Trim(string s, int n)
    {
        s = Esc(s);
        return s.Length <= n ? s : s.Substring(0, n) + "...";
    }

    static bool HasJp(string s)
    {
        if (string.IsNullOrEmpty(s)) return false;
        foreach (char c in s)
            if ((c >= 0x3040 && c <= 0x30FF) || (c >= 0x4E00 && c <= 0x9FFF) || (c >= 0xFF66 && c <= 0xFF9D))
                return true;
        return false;
    }
}
