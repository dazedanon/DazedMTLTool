// Dumps every Japanese string literal out of an IL2CPP game's
// global-metadata.dat using BepInEx's bundled LibCpp2IL parser.
//
// Usage: dotnet run -c Release [-- <output.json> <metadata.dat>]
// Defaults are baked in for SheepClicker.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using AssetRipper.Primitives;
using LibCpp2IL.Metadata;
#pragma warning disable CS0168, CS8321

namespace Il2CppStringDump;

internal static class Program
{
    private static readonly Regex JpRe = new(
        @"[぀-ゟ゠-ヿ一-鿿　-〿]",
        RegexOptions.Compiled);

    /// <summary>
    /// True unless the string looks like a TMP fallback Unicode range table
    /// (those mix CJK with whole non-JP scripts like Devanagari, Thai, etc.).
    /// We use a blacklist instead of a whitelist so legitimate game strings
    /// with arrows (→), × multiplication signs, currency, and other typography
    /// pass through.
    /// </summary>
    private static bool IsRealText(string s)
    {
        if (s.Length > 4000) return false;
        foreach (var c in s)
        {
            // script blocks no JP game text contains; their presence in a
            // string means it's a font/TMP character coverage table
            if (c >= 0x0590 && c <= 0x07FF) return false; // Hebrew, Arabic, Syriac, Thaana
            if (c >= 0x0900 && c <= 0x0FFF) return false; // Indic, Tibetan
            if (c >= 0x1000 && c <= 0x1CFF) return false; // Myanmar..Sundanese
            if (c >= 0x1D00 && c <= 0x1FFF) return false; // Phonetic Ext..Greek Ext
        }
        return true;
    }

    private const string DefaultMetadata =
        @"C:\Users\sw\Desktop\SheepClicker\SheepClicker_Data\il2cpp_data\Metadata\global-metadata.dat";
    private static readonly string DefaultOutput = Path.GetFullPath(
        Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "il2cpp_strings.json"));

    private static int Main(string[] args)
    {
        string metadataPath = args.Length >= 2 ? args[1] : DefaultMetadata;
        string outPath = args.Length >= 1 && args[0] != "-" ? args[0] : DefaultOutput;

        if (!File.Exists(metadataPath))
        {
            Console.Error.WriteLine($"metadata not found: {metadataPath}");
            return 1;
        }

        var bytes = File.ReadAllBytes(metadataPath);
        Console.WriteLine($"loaded {bytes.Length:N0} bytes from {metadataPath}");

        // Unity 6.0.3 — pick something recent enough for v39 metadata.
        var unityVersion = new UnityVersion(6, 0, 3);
        var metadata = Il2CppMetadata.ReadFrom(bytes, unityVersion);
        if (metadata == null)
        {
            Console.Error.WriteLine("Il2CppMetadata.ReadFrom returned null");
            return 2;
        }

        Console.WriteLine($"metadata version: {metadata.MetadataVersion}");

        // We need the raw string-literal data section. Pull it from the header
        // via reflection (the field lives on metadata.metadataHeader.stringLiteralData).
        var headerField = typeof(Il2CppMetadata).GetField(
            "metadataHeader", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
        if (headerField == null) throw new Exception("metadataHeader field missing");
        var header = headerField.GetValue(metadata)
                     ?? throw new Exception("metadataHeader is null");
        var indexSec = header.GetType().GetField("stringLiteral",
            BindingFlags.Public | BindingFlags.Instance)!.GetValue(header)!;
        var dataSec = header.GetType().GetField("stringLiteralData",
            BindingFlags.Public | BindingFlags.Instance)!.GetValue(header)!;

        int indexOffset = (int)indexSec.GetType().GetField("Offset")!.GetValue(indexSec)!;
        int indexSize   = (int)indexSec.GetType().GetField("Size"  )!.GetValue(indexSec)!;
        int indexCount  = (int)indexSec.GetType().GetField("Count" )!.GetValue(indexSec)!;
        int dataOffset  = (int)dataSec.GetType().GetField("Offset")!.GetValue(dataSec)!;
        int dataSize    = (int)dataSec.GetType().GetField("Size"  )!.GetValue(dataSec)!;
        Console.WriteLine($"stringLiteral index : offset=0x{indexOffset:x} size=0x{indexSize:x} count={indexCount}");
        Console.WriteLine($"stringLiteral data  : offset=0x{dataOffset:x} size=0x{dataSize:x}");

        // v39 entry size is 4 bytes (just dataIndex u32). Length is implicit:
        //   length[i] = dataIndex[i+1] - dataIndex[i]  (last one runs to dataSize)
        // v29 and earlier used 8-byte entries (length, dataIndex). Detect by ratio.
        int entryBytes = indexCount > 0 ? indexSize / indexCount : 8;
        Console.WriteLine($"derived entry size: {entryBytes} bytes/entry");

        var offsets = new int[indexCount + 1];
        if (entryBytes == 4)
        {
            for (int k = 0; k < indexCount; k++)
                offsets[k] = BitConverter.ToInt32(bytes, indexOffset + k * 4);
            offsets[indexCount] = dataSize;
        }
        else // assume legacy 8-byte (length, dataIndex)
        {
            for (int k = 0; k < indexCount; k++)
            {
                uint len = BitConverter.ToUInt32(bytes, indexOffset + k * 8);
                int  idx = BitConverter.ToInt32 (bytes, indexOffset + k * 8 + 4);
                offsets[k] = idx;
                offsets[k + 1] = idx + (int)len; // overwritten by next iter unless last
            }
        }

        // Preserve insertion order; merge with existing translations.
        var seen = new Dictionary<string, string>(StringComparer.Ordinal);
        if (File.Exists(outPath))
        {
            try
            {
                foreach (var (k, v) in ReadFlatJson(File.ReadAllText(outPath, Encoding.UTF8)))
                    seen[k] = v;
                Console.WriteLine($"merging into existing {outPath} ({seen.Count} entries)");
            }
            catch (Exception e)
            {
                Console.Error.WriteLine($"warning: existing JSON unreadable: {e.Message}");
            }
        }

        int totalJp = 0;
        int sampled = 0;
        for (int k = 0; k < indexCount; k++)
        {
            int idx = offsets[k];
            int len = offsets[k + 1] - idx;
            if (len <= 0) continue;
            int abs = dataOffset + idx;
            if (abs < 0 || abs + len > bytes.Length) continue;
            string s;
            try { s = Encoding.UTF8.GetString(bytes, abs, len); }
            catch { continue; }
            if (sampled < 6)
            {
                Console.WriteLine($"  [sample {sampled}] len={len} idx=0x{idx:x} s={Trunc(s)}");
                sampled++;
            }
            if (!JpRe.IsMatch(s)) continue;
            if (!IsRealText(s)) continue;
            totalJp++;
            if (!seen.ContainsKey(s)) seen[s] = "";
        }
        Console.WriteLine($"JP scan: {totalJp} usable hits across {indexCount} entries");

        Directory.CreateDirectory(Path.GetDirectoryName(outPath) ?? ".");
        File.WriteAllText(outPath, WriteFlatJson(seen) + "\n", new UTF8Encoding(false));
        Console.WriteLine($"-> {outPath}: {seen.Count} unique JP strings ({totalJp} hits)");
        return 0;
    }

    private static string Trunc(string s)
    {
        if (s.Length <= 80) return $"\"{s.Replace("\n", "\\n")}\"";
        return $"\"{s.Substring(0, 77).Replace("\n", "\\n")}...\"";
    }

    // ---- minimal flat-object JSON helpers ----

    private static IEnumerable<KeyValuePair<string, string>> ReadFlatJson(string s)
    {
        int i = 0;
        SkipWs(s, ref i);
        Expect(s, ref i, '{');
        SkipWs(s, ref i);
        if (i < s.Length && s[i] == '}') yield break;
        while (i < s.Length)
        {
            SkipWs(s, ref i);
            var k = ReadString(s, ref i);
            SkipWs(s, ref i);
            Expect(s, ref i, ':');
            SkipWs(s, ref i);
            var v = ReadString(s, ref i);
            yield return new KeyValuePair<string, string>(k, v);
            SkipWs(s, ref i);
            if (i < s.Length && s[i] == ',') { i++; continue; }
            if (i < s.Length && s[i] == '}') { i++; yield break; }
            throw new FormatException($"expected ',' or '}}' at offset {i}");
        }
    }

    private static string WriteFlatJson(IReadOnlyDictionary<string, string> map)
    {
        var sb = new StringBuilder();
        sb.Append("{\n");
        int n = map.Count, i = 0;
        foreach (var kv in map)
        {
            sb.Append("  ");
            AppendJsonString(sb, kv.Key);
            sb.Append(": ");
            AppendJsonString(sb, kv.Value);
            if (++i < n) sb.Append(',');
            sb.Append('\n');
        }
        sb.Append('}');
        return sb.ToString();
    }

    private static void AppendJsonString(StringBuilder sb, string s)
    {
        sb.Append('"');
        foreach (var c in s)
        {
            switch (c)
            {
                case '"':  sb.Append("\\\""); break;
                case '\\': sb.Append("\\\\"); break;
                case '\n': sb.Append("\\n"); break;
                case '\r': sb.Append("\\r"); break;
                case '\t': sb.Append("\\t"); break;
                case '\b': sb.Append("\\b"); break;
                case '\f': sb.Append("\\f"); break;
                default:
                    if (c < 0x20)
                        sb.Append("\\u").Append(((int)c).ToString("x4"));
                    else
                        sb.Append(c);
                    break;
            }
        }
        sb.Append('"');
    }

    private static void SkipWs(string s, ref int i)
    {
        while (i < s.Length && (s[i] == ' ' || s[i] == '\t' || s[i] == '\r' || s[i] == '\n')) i++;
    }

    private static void Expect(string s, ref int i, char c)
    {
        if (i >= s.Length || s[i] != c) throw new FormatException($"expected '{c}' at offset {i}");
        i++;
    }

    private static string ReadString(string s, ref int i)
    {
        Expect(s, ref i, '"');
        var sb = new StringBuilder();
        while (i < s.Length)
        {
            char c = s[i++];
            if (c == '"') return sb.ToString();
            if (c == '\\' && i < s.Length)
            {
                char e = s[i++];
                switch (e)
                {
                    case '"':  sb.Append('"'); break;
                    case '\\': sb.Append('\\'); break;
                    case '/':  sb.Append('/'); break;
                    case 'n':  sb.Append('\n'); break;
                    case 'r':  sb.Append('\r'); break;
                    case 't':  sb.Append('\t'); break;
                    case 'b':  sb.Append('\b'); break;
                    case 'f':  sb.Append('\f'); break;
                    case 'u':
                        sb.Append((char)Convert.ToInt32(s.Substring(i, 4), 16));
                        i += 4;
                        break;
                    default: sb.Append(e); break;
                }
            }
            else sb.Append(c);
        }
        throw new FormatException("unterminated string");
    }
}
