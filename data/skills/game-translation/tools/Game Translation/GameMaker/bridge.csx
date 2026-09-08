// Noninteractive UTMT 0.9.2.0 bridge. All paths arrive as JSON, never C# source.
using System;
using System.IO;
using System.Linq;
using System.Collections;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UndertaleModLib;
using UndertaleModLib.Models;

EnsureDataLoaded();
var cfg = JObject.Parse(File.ReadAllText(Environment.GetEnvironmentVariable("GMTT_REQUEST")));
var ids = new Dictionary<UndertaleString, int>();
for (int i = 0; i < Data.Strings.Count; i++) ids[Data.Strings[i]] = i;
int Sid(UndertaleString s) => s != null && ids.TryGetValue(s, out int id) ? id : -1;

if ((string)cfg["mode"] == "patch")
{
    if (Data.IsYYC()) throw new Exception("YYC has native code; literal-site patching requires VM bytecode.");
    var changes = (JArray)cfg["changes"];
    var seen = new HashSet<string>();
    foreach (JObject change in changes)
    {
        string site = (string)change["id"];
        if (!seen.Add(site)) throw new Exception("Duplicate site: " + site);
        UndertaleString current;
        if (site == "GEN8:display_name") current = Data.GeneralInfo.DisplayName;
        else
        {
            int ci = (int)change["code_index"], ii = (int)change["instruction_index"];
            if (site != $"CODE:{ci}:{ii}") throw new Exception("Site identity mismatch");
            var code = Data.Code[ci];
            if (code.ParentEntry != null) throw new Exception("Patch the owning parent instruction, not a child alias");
            current = code.Instructions[ii].ValueString?.Resource;
        }
        if (current == null || Sid(current) != (int)change["string_id"] || current.Content != (string)change["source"])
            throw new Exception("Stale source at " + site);
        var replacement = new UndertaleString((string)change["text"]);
        Data.Strings.Add(replacement);
        if (site == "GEN8:display_name") Data.GeneralInfo.DisplayName = replacement;
        else Data.Code[(int)change["code_index"]].Instructions[(int)change["instruction_index"]].ValueString =
            new UndertaleResourceById<UndertaleString, UndertaleChunkSTRG> { Resource = replacement };
    }
    File.WriteAllText((string)cfg["receipt"], JsonConvert.SerializeObject(new { changed = changes.Count }));
}
else if ((string)cfg["mode"] == "snapshot")
{
    var codes = new JArray();
    if (Data.Code != null) for (int ci = 0; ci < Data.Code.Count; ci++)
    {
        var c = Data.Code[ci];
        var instructions = new JArray();
        if (c.ParentEntry == null)
        {
            uint address = 0;
            for (int ii = 0; ii < c.Instructions.Count; ii++)
            {
                var ins = c.Instructions[ii];
                int sid = Sid(ins.ValueString?.Resource);
                instructions.Add(new JObject {
                    ["index"] = ii, ["address_words"] = address,
                    ["size_words"] = ins.CalculateInstructionSize(), ["string_id"] = sid,
                    ["asm"] = sid >= 0 ? ins.Kind.ToString() + "." + ins.Type1.ToString() + ":STRING" : ins.ToString(c, address)
                });
                address += ins.CalculateInstructionSize();
            }
        }
        codes.Add(new JObject {
            ["index"] = ci, ["name"] = c.Name.Content, ["parent"] = c.ParentEntry == null ? -1 : Data.Code.IndexOf(c.ParentEntry),
            ["length"] = c.Length, ["offset"] = c.Offset, ["locals"] = c.LocalsCount,
            ["arguments"] = c.ArgumentsCount, ["instructions"] = instructions
        });
    }
    // Ordered names for every public resource list; these are identities, never translations.
    var resources = new JObject();
    foreach (var prop in typeof(UndertaleData).GetProperties().OrderBy(p => p.Name))
    {
        if (prop.GetIndexParameters().Length != 0 || prop.Name == "Strings") continue;
        if (!typeof(IEnumerable).IsAssignableFrom(prop.PropertyType)) continue;
        if (prop.GetValue(Data) is not IEnumerable list) continue;
        var names = new JArray();
        foreach (var item in list)
        {
            var name = item?.GetType().GetProperty("Name")?.GetValue(item) as UndertaleString;
            names.Add(name?.Content);
        }
        resources[prop.Name] = names;
    }
    var fonts = new JArray();
    if (Data.Fonts != null) foreach (var f in Data.Fonts)
    {
        var glyphs = new JArray();
        foreach (var g in f.Glyphs)
            glyphs.Add(new JObject { ["char"] = g.Character, ["advance"] = g.Shift, ["offset"] = g.Offset,
                ["kerning"] = new JArray(g.Kerning.Select(k => new JObject { ["char"] = k.Character, ["shift"] = k.ShiftModifier })) });
        fonts.Add(new JObject { ["name"] = f.Name.Content, ["face"] = f.DisplayName.Content, ["size"] = f.EmSize,
            ["scale_x"] = f.ScaleX, ["scale_y"] = f.ScaleY, ["line_height"] = f.LineHeight,
            ["bold"] = f.Bold, ["italic"] = f.Italic, ["glyphs"] = glyphs });
    }
    var audio = new JArray();
    if (Data.EmbeddedAudio != null) foreach (var a in Data.EmbeddedAudio)
        audio.Add(Convert.ToHexString(SHA256.HashData(a.Data)).ToLowerInvariant());
    // Hash stored image bytes; do not export or redraw art.
    var textures = new JArray();
    if (Data.EmbeddedTextures != null) foreach (var t in Data.EmbeddedTextures)
    {
        if (t.TextureExternal) { textures.Add("external"); continue; }
        using var imageStream = new MemoryStream();
        using (var imageWriter = new BinaryWriter(imageStream, Encoding.UTF8, true))
            t.TextureData.Image.WriteToBinaryWriter(imageWriter, Data.IsVersionAtLeast(2022, 5));
        textures.Add(Convert.ToHexString(SHA256.HashData(imageStream.ToArray())).ToLowerInvariant());
    }
    var gi = Data.GeneralInfo;
    var report = new JObject {
        ["schema"] = 1, ["backend"] = "UndertaleModTool 0.9.2.0", ["yyc"] = Data.IsYYC(),
        ["version"] = new JArray(gi.Major, gi.Minor, gi.Release, gi.Build), ["bytecode"] = gi.BytecodeVersion,
        ["project"] = gi.Name.Content, ["display_name_id"] = Sid(gi.DisplayName),
        ["window"] = new JArray(gi.DefaultWindowWidth, gi.DefaultWindowHeight),
        ["strings"] = new JArray(Data.Strings.Select(s => s.Content)), ["code"] = codes,
        ["resources"] = resources, ["fonts"] = fonts, ["audio_sha256"] = audio, ["texture_sha256"] = textures
    };
    File.WriteAllText((string)cfg["output"], report.ToString(), new UTF8Encoding(false));
}
else throw new Exception("Unknown bridge mode");
