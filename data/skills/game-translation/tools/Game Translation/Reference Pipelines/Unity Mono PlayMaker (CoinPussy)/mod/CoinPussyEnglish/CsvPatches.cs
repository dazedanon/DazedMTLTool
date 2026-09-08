using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using HarmonyLib;

namespace CoinPussyEnglish
{
    /// <summary>
    /// Layer 1 — swap the game's script CSVs as they are parsed.
    ///
    /// The scripted dialogue lives in five TextAsset CSVs inside resources.assets.
    /// PlayMaker reads them with `ReadTextAsset` and hands the string to
    /// `HutongGames.PlayMaker.Ecosystem.DataMaker.CSV.CsvReader.LoadFromString`,
    /// which is a single static chokepoint every one of them passes through.
    ///
    /// Matching is by SHA-1 of the original file, not by name or header. A CSV the
    /// pipeline never saw simply does not match and is left in Japanese — the patch
    /// can never substitute a stale translation for content it did not translate,
    /// which is the one failure mode that would be invisible in play.
    /// </summary>
    internal static class CsvPatches
    {
        public static int Apply(Harmony harmony)
        {
            var target = AccessTools.Method(
                "HutongGames.PlayMaker.Ecosystem.DataMaker.CSV.CsvReader:LoadFromString");
            if (target == null)
            {
                Plugin.Log.LogError(
                    "CsvReader.LoadFromString not found — the scripted dialogue will stay " +
                    "Japanese. Has the game updated?");
                return 0;
            }
            try
            {
                harmony.Patch(target,
                    prefix: new HarmonyMethod(typeof(CsvPatches), nameof(LoadFromStringPrefix)));
                Plugin.Log.LogInfo("hooked CsvReader.LoadFromString");
                return 1;
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"failed to hook CsvReader.LoadFromString: {e.Message}");
                return 0;
            }
        }

        // The parameter name must match the original method's for Harmony to bind it.
        private static void LoadFromStringPrefix(ref string file_contents)
        {
            if (string.IsNullOrEmpty(file_contents)) return;
            try
            {
                CsvStore.Dump(file_contents);
                if (CsvStore.TryTranslate(file_contents, out var replacement))
                {
                    file_contents = replacement;
                }
            }
            catch (Exception e)
            {
                // Throwing here would escape into the game's CSV parser.
                Plugin.Log.LogWarning($"CSV swap failed: {e.Message}");
            }
        }
    }

    /// <summary>Loads the translated CSVs and resolves them by source checksum.</summary>
    internal static class CsvStore
    {
        // sha1(original, BOM-stripped) -> translated file content
        private static readonly Dictionary<string, string> _bySourceSha =
            new Dictionary<string, string>(StringComparer.Ordinal);
        // sha1 of each translated file, so a second parse of an already-swapped
        // CSV is recognised instead of reported as an unknown file
        private static readonly HashSet<string> _translatedSha =
            new HashSet<string>(StringComparer.Ordinal);
        private static readonly Dictionary<string, string> _nameBySourceSha =
            new Dictionary<string, string>(StringComparer.Ordinal);
        private static readonly HashSet<string> _reportedUnknown =
            new HashSet<string>(StringComparer.Ordinal);
        private static readonly HashSet<string> _dumped =
            new HashSet<string>(StringComparer.Ordinal);

        private static readonly Regex JpRe = new Regex(
            @"[぀-ゟ゠-ヿ一-鿿]", RegexOptions.Compiled);

        public static int Count => _bySourceSha.Count;

        private static string PluginDir =>
            Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location) ?? ".";

        public static void LoadAll()
        {
            var root = Path.Combine(PluginDir, "translations");
            var csvDir = Path.Combine(root, "csv");
            var manifestPath = Path.Combine(root, "csv_manifest.json");

            if (!File.Exists(manifestPath) || !Directory.Exists(csvDir))
            {
                Plugin.Log.LogWarning(
                    $"no CSV manifest at {manifestPath} — scripted dialogue will stay Japanese. " +
                    "Run: python tools/tl.py package");
                return;
            }

            // manifest is a flat { "<sha1 of original>": "<filename>" }
            foreach (var kv in JsonFlat.Parse(File.ReadAllText(manifestPath, Encoding.UTF8)))
            {
                var path = Path.Combine(csvDir, kv.Value);
                if (!File.Exists(path))
                {
                    Plugin.Log.LogWarning($"manifest lists {kv.Value} but it is missing");
                    continue;
                }
                // Stored WITHOUT the BOM; TryTranslate re-attaches one only if the
                // string the game handed us had one. TextAsset.text on this Unity
                // version keeps the mark, and the header key the FSMs look up is the
                // first CSV field — so adding or removing a BOM would silently rename
                // that column.
                var text = StripBom(ReadFileText(path));
                _bySourceSha[kv.Key] = text;
                _nameBySourceSha[kv.Key] = kv.Value;
                _translatedSha.Add(Sha1(text));
            }
            Plugin.Log.LogInfo($"CSV store: {_bySourceSha.Count} translated script files loaded");
        }

        public static bool TryTranslate(string original, out string translated)
        {
            translated = null;
            var body = StripBom(original);
            var sha = Sha1(body);

            if (_bySourceSha.TryGetValue(sha, out var tl))
            {
                // Preserve the caller's BOM state exactly.
                translated = ReferenceEquals(body, original) ? tl : "﻿" + tl;
                if (Plugin.CfgVerbose?.Value == true)
                {
                    Plugin.Log.LogInfo($"CSV swap: {_nameBySourceSha[sha]} " +
                                       $"({original.Length} -> {translated.Length} chars)");
                }
                return true;
            }

            if (_translatedSha.Contains(sha)) return false;   // already swapped, parsed again
            ReportUnknown(sha, original);
            return false;
        }

        public static void Dump(string content)
        {
            if (Plugin.CfgDumpCsv?.Value != true || string.IsNullOrEmpty(content)) return;
            try
            {
                var sha = Sha1(StripBom(content));
                lock (_dumped)
                {
                    if (!_dumped.Add(sha)) return;
                }
                var dir = Path.Combine(PluginDir, "dump");
                Directory.CreateDirectory(dir);
                File.WriteAllText(Path.Combine(dir, sha + ".csv"), content,
                                  new UTF8Encoding(false));
            }
            catch { /* dumping must never break the game */ }
        }

        private static void ReportUnknown(string sha, string original)
        {
            if (!JpRe.IsMatch(original)) return;      // not a script CSV we care about
            lock (_reportedUnknown)
            {
                if (!_reportedUnknown.Add(sha)) return;
            }
            var head = original;
            int nl = head.IndexOfAny(new[] { '\r', '\n' });
            if (nl > 0) head = head.Substring(0, nl);
            Plugin.Log.LogWarning(
                $"CSV not in the manifest, left in Japanese (sha1 {sha.Substring(0, 12)}, " +
                $"{original.Length} chars, header \"{head}\"). Either the game updated or " +
                "this file was never extracted — re-run: python tools/scripts/dump_textassets.py " +
                "&& python tools/tl.py extract. Set DumpLoadedCsv=true to capture it.");
        }

        /// <summary>Read a file as UTF-8 without letting the decoder eat the BOM,
        /// so BOM handling stays in one place (StripBom / TryTranslate).</summary>
        private static string ReadFileText(string path)
            => new UTF8Encoding(false).GetString(File.ReadAllBytes(path));

        /// <summary>Returns the same instance when there is no BOM, which lets the
        /// caller detect the BOM with a reference comparison.</summary>
        private static string StripBom(string s)
            => (s.Length > 0 && s[0] == '﻿') ? s.Substring(1) : s;

        private static string Sha1(string s)
        {
            using (var sha = SHA1.Create())
            {
                var hash = sha.ComputeHash(new UTF8Encoding(false).GetBytes(s));
                var sb = new StringBuilder(hash.Length * 2);
                foreach (var b in hash) sb.Append(b.ToString("x2"));
                return sb.ToString();
            }
        }
    }
}
