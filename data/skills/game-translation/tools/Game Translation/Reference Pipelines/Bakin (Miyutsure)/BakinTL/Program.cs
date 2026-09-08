using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using Yukar.Common;
using Yukar.Common.Resource;
using Yukar.Common.Rom;

// Dump/inject the LocalizeData chunk of a DESCRAMBLED Bakin project folder,
// using the game's own common.dll so the rom parse is the engine's parse.
static class Program
{
    static readonly Guid LOCALIZE_CHUNK = new Guid("FA43A17A-FF3E-48BA-9E63-CB765A2FC514");

    [System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
    static extern bool SetDllDirectory(string path);

    static string sDataDir;

    static int Main(string[] args)
    {
        Console.OutputEncoding = Encoding.UTF8;
        // The engine assemblies stay in the game folder; bind to them from here so
        // the tool is not tied to one game's copy.
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
        switch (args[0])
        {
            case "probe": return Probe(proj);
            case "dump": return Dump(proj, args.Length > 2 ? args[2] : "units.tsv");
            case "audit": return Audit(proj, args.Length > 2 ? args[2] : "audit.tsv");
            case "roundtrip": return RoundTrip(proj);
            case "export": return Export(proj, args.Length > 2 ? args[2] : ".");
            case "resources": return Resources(proj, args.Length > 2 ? args[2] : "resources.tsv");
            case "layout": return Layout(proj, args.Length > 2 ? args[2] : "layout.tsv");
            case "effectparams": return EffectParams(proj, args.Length > 2 ? args[2] : "effectparams.tsv");
            case "fonts": return Fonts(proj, args.Length > 2 ? args[2] : "fonts.tsv");
            case "inject":
                if (args.Length < 4) { Usage(); return 2; }
                return Inject(proj, args[2], args[3]);
            default: Usage(); return 2;
        }
    }

    static void Usage()
    {
        Console.Error.WriteLine("BakinTL probe     <projDir>");
        Console.Error.WriteLine("BakinTL dump      <projDir> <out.tsv>");
        Console.Error.WriteLine("BakinTL audit     <projDir> <out.tsv>");
        Console.Error.WriteLine("BakinTL roundtrip <projDir>");
        Console.Error.WriteLine("BakinTL export    <projDir> <outDir>");
        Console.Error.WriteLine("BakinTL inject    <projDir> <translated.jsonl> <outDir>");
    }

    static Catalog LoadCatalog(string proj)
    {
        Catalog.sResourceDir = proj + Path.DirectorySeparatorChar;
        var catalog = new Catalog(false);
        Catalog.sInstance = catalog;
        // Texture.load / Model.load construct native SharpKmyGfx objects and need a
        // live renderer; this is the engine's own switch for loading a catalog
        // without one, and it is what makes ResourceItem.rbr readable here.
        ResourceItem.sAttachResource = false;
        var files = Directory.GetFiles(proj, "*.rbr", SearchOption.TopDirectoryOnly).ToList();
        string mapDir = Path.Combine(proj, "map");
        if (Directory.Exists(mapDir)) files.AddRange(Directory.GetFiles(mapDir, "*.rbr", SearchOption.TopDirectoryOnly));
        // GameSettings must land first: everything else resolves against it.
        files = files.OrderBy(f => Path.GetFileName(f).Equals("GameSettings.rbr", StringComparison.OrdinalIgnoreCase) ? 0 : 1).ToList();
        foreach (var f in files)
        {
            using (var fs = File.OpenRead(f))
                catalog.load(Catalog.FileType.RBR, fs, Catalog.OVERWRITE_RULES.NEVER, true);
        }
        // Folders serialise Childs, not ChildIds; without this the writer emits
        // every folder empty and the tree is silently destroyed on save.
        foreach (Folder folder in catalog.getFilteredItemList<Folder>())
            folder.initialize(catalog, false);
        var gs = catalog.getGameSettings(false);
        if (gs != null) gs.initCommonEventListInfo(catalog);
        return catalog;
    }

    static int Probe(string proj)
    {
        var catalog = LoadCatalog(proj);
        Console.WriteLine("scripts        : " + catalog.getFilteredItemList<Script>().Count);
        Console.WriteLine("maps           : " + catalog.getFilteredItemList(typeof(Map), false).Count);
        Console.WriteLine("gameSettings   : " + (catalog.getGameSettings(false) != null));
        var lp = catalog.getLayoutProperties();
        Console.WriteLine("layoutProps    : " + (lp != null));
        if (lp != null) Console.WriteLine("layoutNodes    : " + lp.AllLayoutNodes.Count());
        Console.WriteLine("localizeChunks : " + catalog.getFilteredExtraChunkList(LOCALIZE_CHUNK).Count);
        return 0;
    }

    static int Dump(string proj, string outPath)
    {
        var catalog = LoadCatalog(proj);
        var chunks = catalog.getFilteredExtraChunkList(LOCALIZE_CHUNK);
        if (chunks.Count == 0) { Console.Error.WriteLine("no LocalizeData chunk"); return 1; }

        // Index every localizable target the way LocalizedCatalog.ApplyLocalization does.
        var scriptAttr = new Dictionary<Guid, Tuple<Script, int, int>>();
        foreach (var s in catalog.getFilteredItemList<Script>().Cast<Script>())
        {
            for (int ci = 0; ci < s.commands.Count; ci++)
            {
                var cmd = s.commands[ci];
                for (int ai = 0; ai < cmd.attrList.Count; ai++)
                {
                    var sa = cmd.attrList[ai] as Script.StringAttr;
                    if (sa != null && sa.guid.HasValue) scriptAttr[sa.guid.Value] = Tuple.Create(s, ci, ai);
                }
            }
        }
        var menuItem = new Dictionary<Guid, object>();
        var lp = catalog.getLayoutProperties();
        if (lp != null)
        {
            foreach (var node in lp.AllLayoutNodes)
                foreach (var mi in node.MenuSettings.ParseAllItems())
                    menuItem[mi.guid] = mi;
        }

        Console.WriteLine("script string attrs: " + scriptAttr.Count);
        Console.WriteLine("menu items         : " + menuItem.Count);
        int found = 0, missing = 0;
        using (var w = new StreamWriter(outPath, false, new UTF8Encoding(false)))
        {
            w.WriteLine("guid\ttypeName\tpropertyName\townerName\tcontext\tsource");
            foreach (var t in ReadTexts(chunks[0]))
            {
                string owner = "", context = "", src = null;
                if (t.Item1 == "Script")
                {
                    Tuple<Script, int, int> hit;
                    if (scriptAttr.TryGetValue(t.Item3, out hit))
                    {
                        var sa = (Script.StringAttr)hit.Item1.commands[hit.Item2].attrList[hit.Item3];
                        src = sa.value;
                        owner = hit.Item1.name ?? "";
                        context = hit.Item1.guId + "#" + hit.Item2 + "#" + hit.Item3 + "#" + hit.Item1.commands[hit.Item2].type;
                    }
                }
                else if (t.Item1 == "LayoutNode")
                {
                    object mi;
                    if (menuItem.TryGetValue(t.Item3, out mi))
                    {
                        src = GetField(mi, t.Item2);
                        owner = GetField(mi, "name") ?? "";
                        context = mi.GetType().Name;
                    }
                }
                else if (t.Item1 == "Glossary")
                {
                    var g = catalog.getGameSettings(true).glossary;
                    src = GetField(g, t.Item2);
                    owner = "Glossary";
                    context = "Glossary";
                }
                else
                {
                    var rom = catalog.getItemFromGuid(t.Item3, false);
                    if (rom != null)
                    {
                        src = GetField(rom, t.Item2);
                        owner = rom.name ?? "";
                        context = rom.GetType().Name;
                    }
                }
                if (src == null) missing++; else found++;
                w.WriteLine(string.Join("\t", new string[]{
                    t.Item3.ToString(), t.Item1, t.Item2, Esc(owner), Esc(context), Esc(src ?? "")}));
            }
        }
        Console.WriteLine("resolved " + found + " / missing " + missing);
        return 0;
    }

    // Every Script command with all of its attributes, so the translation driver
    // can see a scene rather than a bag of lines, and so attribute indices that
    // hold keys (asset paths, blend-shape names) can be told apart from prose.
    static int Export(string proj, string outDir)
    {
        var catalog = LoadCatalog(proj);
        Directory.CreateDirectory(outDir);

        var mapOfScript = new Dictionary<Guid, string>();
        foreach (Map map in catalog.getFilteredItemList(typeof(Map), false).Cast<Map>())
            foreach (var er in map.getEvents())
            {
                var ev = catalog.getItemFromGuid(er.guId, false) as Event;
                if (ev == null) continue;
                foreach (var sheet in ev.sheetList)
                    mapOfScript[sheet.script] = map.name + " / " + (ev.name ?? "");
            }

        int nCmd = 0;
        using (var w = new StreamWriter(Path.Combine(outDir, "scripts.jsonl"), false, new UTF8Encoding(false)))
        {
            foreach (var s in catalog.getFilteredItemList<Script>().Cast<Script>())
            {
                var sb = new StringBuilder();
                string owner;
                if (!mapOfScript.TryGetValue(s.guId, out owner)) owner = "(common)";
                sb.Append("{\"guid\":").Append(J(s.guId.ToString()))
                  .Append(",\"name\":").Append(J(s.name ?? ""))
                  .Append(",\"owner\":").Append(J(owner))
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

        int n = 0;
        // JSONL, not TSV: the engine's own escapes (\n, \\, \c[..]) live inside these
        // strings and a second escaping layer of our own would be ambiguous with them.
        using (var w = new StreamWriter(Path.Combine(outDir, "units.jsonl"), false, new UTF8Encoding(false)))
        {
            Action<string, string, string, string, string> emit = (key, kind, owner, ctx, val) =>
            {
                if (!HasJp(val)) return;
                w.WriteLine("{\"key\":" + J(key) + ",\"kind\":" + J(kind) + ",\"owner\":" + J(owner)
                            + ",\"ctx\":" + J(ctx) + ",\"src\":" + J(val) + "}");
                n++;
            };
            foreach (var s in catalog.getFilteredItemList<Script>().Cast<Script>())
            {
                string owner;
                if (!mapOfScript.TryGetValue(s.guId, out owner)) owner = "(common)";
                for (int ci = 0; ci < s.commands.Count; ci++)
                {
                    var cmd = s.commands[ci];
                    if (KEY_COMMANDS.Contains(cmd.type.ToString())) continue;
                    for (int ai = 0; ai < cmd.attrList.Count; ai++)
                    {
                        var sa = cmd.attrList[ai] as Script.StringAttr;
                        if (sa == null) continue;
                        emit("S:" + s.guId + ":" + ci + ":" + ai, "Script." + cmd.type,
                             owner, s.name + "#" + ci + "." + ai, sa.value);
                    }
                }
            }
            // Keyed by (node, position), never by MenuItem.guid: duplicating a layout
            // in the editor clones the item guids too, and 162 of them collide here.
            foreach (var node in LayoutNodes(catalog))
            {
                int mi_i = 0;
                foreach (var mi in node.MenuSettings.ParseAllItems())
                {
                    foreach (var f in LocalizableFields(mi.GetType()))
                        emit("M:" + node.Guid + ":" + mi_i + ":" + f.Name, "MenuItem." + f.Name,
                             node.Name, GetField(mi, "name") ?? "", (string)f.GetValue(mi));
                    mi_i++;
                }
            }

            foreach (var rom in catalog.getFilteredItemList(typeof(RomItem), false))
            {
                string tn = rom.GetType().Name;
                if (KEY_ROMS.Contains(tn)) continue;
                foreach (var f in LocalizableFields(rom.GetType()))
                    emit("R:" + rom.guId + ":" + f.Name, tn + "." + f.Name, tn, rom.name ?? "",
                         (string)f.GetValue(rom));
            }
            var gl = catalog.getGameSettings(true).glossary;
            foreach (var f in gl.GetType().GetFields())
                if (f.FieldType == typeof(string))
                    emit("G:" + f.Name, "Glossary." + f.Name, "Glossary", f.Name, (string)f.GetValue(gl));
        }
        Console.WriteLine("commands " + nCmd + " / units " + n + " -> " + outDir);
        return 0;
    }

    // Every asset the catalog knows about, by rom type. Type is what separates 2D
    // art that can carry baked text (Sprite, Window, Icon, Face, backgrounds) from
    // the model textures that make up most of the corpus by size.
    static int Resources(string proj, string outPath)
    {
        var catalog = LoadCatalog(proj);
        var byType = new SortedDictionary<string, int[]>();
        using (var w = new StreamWriter(outPath, false, new UTF8Encoding(false)))
        {
            w.WriteLine("guid\ttype\tname\tpath");
            foreach (ResourceItem r in catalog.getFiltered<ResourceItem>())
            {
                string t = r.GetType().Name;
                int[] c;
                if (!byType.TryGetValue(t, out c)) byType[t] = c = new int[1];
                c[0]++;
                w.WriteLine(string.Join("\t", new string[] { r.guId.ToString(), t, Esc(r.name ?? ""), Esc(r.path ?? "") }));
            }
        }
        foreach (var kv in byType) Console.WriteLine(kv.Key.PadRight(24) + kv.Value[0]);
        return 0;
    }

    // The geometry that decides whether a translation overflows. Every field the
    // engine consults is layout DATA, so the fitting model has to be measured per
    // widget rather than assumed for the game:
    //   useMultiLineText -> auto word-wrap to size.X (width becomes soft)
    //   maxLineNum       -> auto-pagination (height becomes soft)
    //   useClipping      -> text past the box is CUT, not just overlapping
    //   sizeType=AUTO    -> the widget grows to its content and can hit a neighbour
    static int Layout(string proj, string outPath)
    {
        var catalog = LoadCatalog(proj);
        int rows = 0;
        using (var w = new StreamWriter(outPath, false, new UTF8Encoding(false)))
        {
            w.WriteLine(string.Join("\t", new string[] { "nodeGuid", "node", "idx", "itemType", "name",
                "sizeType", "sizeX", "sizeY", "scaleX", "wordWrap", "clipping", "scrollBar",
                "maxLineNum", "lineOffset", "font",
                "usage", "nodeType", "layoutType",
                "posX", "posY", "offsetX", "offsetY", "origin", "posType", "image", "useText",
                "subW", "subH", "subMargin", "subBg", "windowImg", "parent",
                "text" }));
            foreach (var node in LayoutNodes(catalog))
            {
                var ms = node.MenuSettings;
                // ParseAllItems FLATTENS the tree, and a flat list cannot say what a
                // label is drawn on top of - which is what decides its real bound.
                // Rebuild the parent link by matching object identity against that
                // same flat list, never by re-deriving the order.
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
                        node.Guid.ToString(), Esc(node.Name ?? ""), i.ToString(), mi.itemType.ToString(),
                        Esc(GetField(mi, "name") ?? ""),
                        mi.sizeType.ToString(),
                        mi.size.X.ToString("0.##"), mi.size.Y.ToString("0.##"),
                        mi.scale.X.ToString("0.###"),
                        mi.useMultiLineText ? "1" : "0",
                        mi.useClipping ? "1" : "0",
                        mi.UseScrollBar ? "1" : "0",
                        ms.maxLineNum.ToString(), ms.lineOffset.ToString(),
                        mi.font == Guid.Empty ? "" : FontName(catalog, mi.font),
                        node.Usage.ToString(), node.NodeType.ToString(),
                        mi.layoutType.ToString(),
                        mi.pos.X.ToString("0.##"), mi.pos.Y.ToString("0.##"),
                        mi.offset.X.ToString("0.##"), mi.offset.Y.ToString("0.##"),
                        mi.origin.ToString(), mi.posType.ToString(),
                        mi.image == Guid.Empty ? "" : mi.image.ToString(),
                        mi.useText ? "1" : "0",
                        mi.subItemsBaseWidth.ToString("0.##"),
                        mi.subItemsBaseHeight.ToString("0.##"),
                        mi.subItemMergin.Y.ToString("0.##"),
                        mi.subItemBaseBackground == Guid.Empty
                            ? "" : mi.subItemBaseBackground.ToString(),
                        // `window` is the container's own FRAME, and it is not
                        // `image` (a sprite) nor `subItemBaseBackground` (the
                        // plate under each sub-item row). Emitting only `image`
                        // reports a fully framed screen as having no art, which
                        // is how a battle-result plate stayed invisible for a
                        // whole debugging session.
                        mi.window == Guid.Empty ? "" : mi.window.ToString(),
                        parentOf.ContainsKey(i) ? parentOf[i].ToString() : "-1",
                        Esc(GetField(mi, "text") ?? "") }));
                    i++; rows++;
                }
            }
        }
        Console.WriteLine("layout rows " + rows + " -> " + outPath);
        return 0;
    }

    // Rendered width is MeasureString(font at Font.Size, s).X * MenuItem.scale.X,
    // so the base size lives here and nowhere else. UseToMessageDefault /
    // UseToLayoutDefault name the font a widget gets when MenuItem.font is empty.
    static int Fonts(string proj, string outPath)
    {
        var catalog = LoadCatalog(proj);
        var gs = catalog.getGameSettings(true);
        Console.WriteLine("default message font: " + FontName(catalog, gs.UseToMessageDefault));
        Console.WriteLine("default layout  font: " + FontName(catalog, gs.UseToLayoutDefault));
        Console.WriteLine();
        using (var w = new StreamWriter(outPath, false, new UTF8Encoding(false)))
        {
            w.WriteLine(string.Join("\t", new string[] { "guid", "name", "size", "defaultScale",
                "rubyScale", "lineOffset", "yOffset", "type", "family", "msgDefault",
                "layoutDefault", "path" }));
            foreach (Yukar.Common.Resource.Font f in catalog.getFiltered<Yukar.Common.Resource.Font>())
            {
                w.WriteLine(string.Join("\t", new string[] {
                    f.guId.ToString(), Esc(f.name ?? ""), f.Size.ToString(),
                    f.DefaultScale.ToString("0.###"), f.RubyScale.ToString("0.###"),
                    f.LineOffset.ToString(), f.YOffset.ToString(), f.Type.ToString(),
                    Esc(f.fontFamily ?? ""),
                    f.UseToMessageDefault ? "1" : "0", f.UseToLayoutDefault ? "1" : "0",
                    Esc(f.Path ?? "") }));
                Console.WriteLine(string.Format("{0,-24} size={1,-4} scale={2,-6} msgDef={3} layoutDef={4} {5}",
                    (f.name ?? "").PadRight(24).Substring(0, 24), f.Size, f.DefaultScale,
                    f.UseToMessageDefault, f.UseToLayoutDefault, f.Path));
            }
        }
        return 0;
    }

    static string FontName(Catalog c, Guid g)
    {
        var r = c.getItemFromGuid(g, false);
        return r == null ? g.ToString() : (r.name ?? "");
    }

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
        var scripts = catalog.getFilteredItemList<Script>().Cast<Script>().ToDictionary(s => s.guId);
        var menuItems = new Dictionary<string, object>();
        foreach (var node in LayoutNodes(catalog))
        {
            int mi_i = 0;
            foreach (var mi in node.MenuSettings.ParseAllItems())
                menuItems[node.Guid + ":" + mi_i++] = mi;
        }

        int applied = 0;
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
                    if (sa != null) { sa.value = kv.Value; ok = true; }
                }
            }
            else if (p[0] == "M" && p.Length == 4)
            {
                object mi;
                if (menuItems.TryGetValue(p[1] + ":" + p[2], out mi)) ok = SetField(mi, p[3], kv.Value);
            }
            else if (p[0] == "R" && p.Length == 3)
            {
                var rom = catalog.getItemFromGuid(new Guid(p[1]), false);
                if (rom != null) ok = SetField(rom, p[2], kv.Value);
            }
            else if (p[0] == "G" && p.Length == 2)
            {
                ok = SetField(catalog.getGameSettings(true).glossary, p[1], kv.Value);
            }
            if (ok) applied++; else unmatched.Add(kv.Key);
        }
        Console.WriteLine("applied " + applied + " / unmatched " + unmatched.Count);
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
        Directory.Delete(Path.Combine(outDir, "backup"), true);
        Console.WriteLine("save rc=" + rc + " -> " + outDir);
        Compare(proj, outDir);
        return rc;
    }

    static IEnumerable<LayoutProperties.LayoutNode> LayoutNodes(Catalog c)
    {
        var lp = c.getLayoutProperties();
        return lp == null ? Enumerable.Empty<LayoutProperties.LayoutNode>() : lp.AllLayoutNodes;
    }

    // Walk a path like EffectParamSettings.EffectParamList[3].ChangeParam and hand
    // back the object owning the last segment. Null when any hop is missing, so a
    // stale index can never write into the wrong element.
    static object ResolvePath(object o, string[] parts, int upto)
    {
        for (int i = 0; i < upto && o != null; i++)
        {
            string seg = parts[i];
            int br = seg.IndexOf('[');
            string nm = br < 0 ? seg : seg.Substring(0, br);
            object next = null;
            var pi = o.GetType().GetProperty(nm);
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
                if (!int.TryParse(seg.Substring(br + 1).TrimEnd(']'), out idx)) return null;
                var en = next as System.Collections.IEnumerable;
                if (en == null) return null;
                object found = null; int k = 0;
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
        // A DOTTED path addresses something NESTED. A rom item can hold player text
        // inside a list behind a property, where a flat field table cannot reach it
        // and the engine reads THAT copy rather than the flat one.
        if (name.IndexOf('.') >= 0)
        {
            var parts = name.Split('.');
            object holder = ResolvePath(o, parts, parts.Length - 1);
            if (holder == null) return false;
            string last = parts[parts.Length - 1];
            var pp = holder.GetType().GetProperty(last);
            if (pp != null && pp.PropertyType == typeof(string) && pp.CanWrite)
            { pp.SetValue(holder, value, null); return true; }
            var ff = holder.GetType().GetField(last);
            if (ff != null && ff.FieldType == typeof(string))
            { ff.SetValue(holder, value); return true; }
            return false;
        }
        // LAYOUT GEOMETRY. `pos` and `scale` are XNA Vector2 STRUCTS, so GetValue
        // hands back a boxed copy - mutate the box and write it back, or the
        // assignment is silently lost. A scale of 0 erases the text, so guard it.
        if (name == "posX" || name == "posY" || name == "scaleX" || name == "scaleY")
        {
            bool isPos = name[0] == 'p';
            var pf = o.GetType().GetField(isPos ? "pos" : "scale");
            if (pf == null || pf.FieldType.Name != "Vector2") return false;
            float v;
            if (!float.TryParse(value, System.Globalization.NumberStyles.Float,
                                System.Globalization.CultureInfo.InvariantCulture, out v))
                return false;
            if (!isPos && (v <= 0f || v > 8f)) return false;
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

    // ------------------------------------------------- nested effect params
    //
    // A Condition can store its battle messages TWICE: the flat messageFor* family,
    // and again inside EffectParamSettings.EffectParamList[], where a
    // ChangeStringParamEffectParamBase element holds the same string. The ENGINE
    // reads the nested copy, so translating only the flat one leaves the source
    // language on screen while every unit in the store is translated.
    //
    // A flat field table cannot reach it, so the list is dumped WITH ITS INDEX -
    // that index is what makes a write address possible at all.
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
                        foreach (var pr in el.GetType().GetProperties(
                                     BindingFlags.Public | BindingFlags.Instance))
                        {
                            if (pr.PropertyType != typeof(string)) continue;
                            if (!pr.CanRead || !pr.CanWrite) continue;
                            if (pr.GetIndexParameters().Length != 0) continue;
                            string v = null;
                            try { v = (string)pr.GetValue(el, null); } catch { continue; }
                            if (string.IsNullOrEmpty(v)) continue;
                            w.WriteLine(string.Join("\t", new string[] {
                                rom.guId.ToString(), rom.GetType().Name,
                                Esc(rom.name ?? ""), i.ToString(), pr.Name, Esc(v) }));
                            rows++;
                        }
                    i++;
                }
            }
        }
        Console.WriteLine("effect param strings " + rows + " -> " + outPath);
        return 0;
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

    // Command types whose string attributes are asset paths or engine keys.
    static readonly HashSet<string> KEY_COMMANDS = new HashSet<string> {
        "COMMENT", "SPPICTURE", "CHANGE_RENDER", "PLGRAPHIC" };

    // Rom types whose name is editor-only and never drawn.
    static readonly HashSet<string> KEY_ROMS = new HashSet<string> {
        "Script", "Event", "Folder", "Camera", "RenderSettings", "ResourceItem" };

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
        // ConditionAttr and friends throw from GetValue().
        try { return a.GetType().Name + ":" + (a.GetValue() ?? ""); }
        catch (NotImplementedException) { return a.GetType().Name; }
    }

    static string J(string s)
    {
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

    // Load each rom file on its own and write it straight back. Until this
    // reports 0 differing bytes, no injected build can be trusted: a diff here
    // is the engine's own writer disagreeing with its own reader.
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

    // Resolved lazily: touching Catalog from a static initializer would run
    // before Main installs the AssemblyResolve hook.
    static FieldInfo sItemList;

    static List<RomItem> ItemList(Catalog c)
    {
        if (sItemList == null)
            sItemList = typeof(Catalog).GetField("itemList", BindingFlags.NonPublic | BindingFlags.Instance);
        return (List<RomItem>)sItemList.GetValue(c);
    }

    static bool HasJp(string s)
    {
        if (string.IsNullOrEmpty(s)) return false;
        foreach (char c in s)
            if ((c >= 0x3040 && c <= 0x30FF) || (c >= 0x4E00 && c <= 0x9FFF) || (c >= 0xFF66 && c <= 0xFF9D))
                return true;
        return false;
    }

    // Every Japanese-bearing string the engine can reach, and whether the
    // LocalizeData table has a slot for it. Anything uncovered here is text the
    // official localization path physically cannot translate.
    static int Audit(string proj, string outPath)
    {
        var catalog = LoadCatalog(proj);
        var chunks = catalog.getFilteredExtraChunkList(LOCALIZE_CHUNK);
        var slots = new HashSet<Guid>();
        if (chunks.Count > 0) foreach (var t in ReadTexts(chunks[0])) slots.Add(t.Item3);

        var w = new StreamWriter(outPath, false, new UTF8Encoding(false));
        w.WriteLine("kind\tcovered\towner\tdetail\tvalue");
        var tally = new SortedDictionary<string, int[]>();
        Action<string, bool, string, string, string> rec = (kind, cov, owner, detail, val) =>
        {
            if (!HasJp(val)) return;
            int[] c;
            if (!tally.TryGetValue(kind, out c)) tally[kind] = c = new int[2];
            c[cov ? 0 : 1]++;
            w.WriteLine(string.Join("\t", new string[] { kind, cov ? "YES" : "NO", Esc(owner), Esc(detail), Esc(val) }));
        };

        foreach (var s in catalog.getFilteredItemList<Script>().Cast<Script>())
        {
            foreach (var cmd in s.commands)
                foreach (var a in cmd.attrList)
                {
                    var sa = a as Script.StringAttr;
                    if (sa == null) continue;
                    rec("Script." + cmd.type, sa.guid.HasValue && slots.Contains(sa.guid.Value),
                        s.name ?? "", cmd.type.ToString(), sa.value);
                }
        }
        var lp = catalog.getLayoutProperties();
        if (lp != null)
            foreach (var node in lp.AllLayoutNodes)
                foreach (var mi in node.MenuSettings.ParseAllItems())
                    foreach (var f in LocalizableFields(mi.GetType()))
                        rec("MenuItem." + f.Name, slots.Contains(mi.guid), node.Name, mi.GetType().Name, (string)f.GetValue(mi));

        foreach (var rom in catalog.getFilteredItemList(typeof(RomItem), false))
            foreach (var f in LocalizableFields(rom.GetType()))
                rec(rom.GetType().Name + "." + f.Name, slots.Contains(rom.guId), rom.name ?? "", rom.GetType().Name, (string)f.GetValue(rom));

        var gl = catalog.getGameSettings(true).glossary;
        foreach (var f in gl.GetType().GetFields())
            if (f.FieldType == typeof(string))
                rec("Glossary." + f.Name, true, "Glossary", "Glossary", (string)f.GetValue(gl));
        w.Close();

        Console.WriteLine("kind".PadRight(34) + "covered  uncovered");
        int tc = 0, tu = 0;
        foreach (var kv in tally)
        {
            Console.WriteLine(kv.Key.PadRight(34) + kv.Value[0].ToString().PadLeft(7) + kv.Value[1].ToString().PadLeft(11));
            tc += kv.Value[0]; tu += kv.Value[1];
        }
        Console.WriteLine("TOTAL".PadRight(34) + tc.ToString().PadLeft(7) + tu.ToString().PadLeft(11));
        return 0;
    }

    static IEnumerable<FieldInfo> LocalizableFields(Type t)
    {
        foreach (var f in t.GetFields())
            if (f.FieldType == typeof(string) && f.GetCustomAttributes(typeof(LocalizableAttribute), true).Length > 0)
                yield return f;
    }

    static string Esc(string s)
    {
        if (s == null) return "";
        return s.Replace("\\", "\\\\").Replace("\t", "\\t").Replace("\r", "\\r").Replace("\n", "\\n");
    }

    static string GetField(object o, string name)
    {
        if (o == null) return null;
        var f = o.GetType().GetField(name);
        if (f == null || f.FieldType != typeof(string)) return null;
        return (string)f.GetValue(o);
    }

    // (typeName, propertyName, guid) for every LocalizableText in the chunk.
    static IEnumerable<Tuple<string, string, Guid>> ReadTexts(ExtraChunk chunk)
    {
        var buf = (byte[])typeof(ExtraChunk).GetField("buffer", BindingFlags.NonPublic | BindingFlags.Instance).GetValue(chunk);
        var result = new List<Tuple<string, string, Guid>>();
        using (var ms = new MemoryStream(buf))
        using (var r = new BinaryReader(ms, Encoding.UTF8))
        {
            r.ReadInt32();                       // chunk payload length
            int nl = r.ReadInt32();
            for (int i = 0; i < nl; i++) { int n = r.ReadInt32(); r.ReadBytes(n); }
            int nt = r.ReadInt32();
            for (int i = 0; i < nt; i++)
            {
                int n = r.ReadInt32();
                var sub = r.ReadBytes(n);
                using (var sr = new BinaryReader(new MemoryStream(sub), Encoding.UTF8))
                    result.Add(Tuple.Create(sr.ReadString(), sr.ReadString(), new Guid(sr.ReadBytes(16))));
            }
        }
        return result;
    }
}
