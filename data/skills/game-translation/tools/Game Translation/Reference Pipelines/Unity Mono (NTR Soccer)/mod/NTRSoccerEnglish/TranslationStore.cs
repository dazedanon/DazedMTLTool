using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;

namespace NTRSoccerEnglish
{
    /// <summary>
    /// Loads JSON translation files at startup and serves runtime lookups.
    /// JSON shape: { "<japanese>": "<english>" }. Empty values are skipped.
    /// Ported from SheepClickerTL (hand-rolled flat JSON parser, format-string
    /// pattern matching for {0}-style templates, compose fallback for
    /// concatenated strings, hot-path hit/miss caches).
    /// </summary>
    internal static class TranslationStore
    {
        private static readonly ConcurrentDictionary<string, string> _map =
            new ConcurrentDictionary<string, string>(StringComparer.Ordinal);

        // cache of normalized -> original key, used for forgiving newline matches
        private static readonly ConcurrentDictionary<string, string> _normIndex =
            new ConcurrentDictionary<string, string>(StringComparer.Ordinal);

        // Format-string patterns. JP "得点 {0}/{1}" -> EN "Score {0}/{1}".
        // JP is compiled into a regex capturing the runtime values, which are
        // then spliced into the EN template. Immune to whether the game built
        // the string via String.Format, interpolation, or +-concat.
        private sealed class FormatPattern
        {
            public Regex Regex;           // ^literal(.*?)literal$ — full input match
            public Regex RegexAtStart;    // \G variant — matches at walker position
            public string Template;       // EN template with {0},{1},...
            public string FirstLiteral;   // first literal chunk, used as a fast skip
            public int LiteralLen;        // total literal length, sorts by specificity
            public int[] Slots;           // Slots[g-1] = placeholder index captured by group g
        }
        private static readonly List<FormatPattern> _patterns = new List<FormatPattern>();
        // .NET composite format: {index[,alignment][:format]}
        private static readonly Regex PlaceholderRe = new Regex(
            @"\{\d+(?:,-?\d+)?(?::[^{}]*)?\}", RegexOptions.Compiled);

        // captured runtime values can't contain Japanese — that's the
        // signature of a pattern over-matching.
        private static readonly Regex JpRe = new Regex(
            @"[぀-ゟ゠-ヿ一-鿿]", RegexOptions.Compiled);

        private static readonly ConcurrentDictionary<string, string> _hitCache =
            new ConcurrentDictionary<string, string>(StringComparer.Ordinal);
        private static readonly ConcurrentDictionary<string, byte> _missCache =
            new ConcurrentDictionary<string, byte>(StringComparer.Ordinal);

        // exact-match keys sorted by length descending, for the compose fallback
        private static readonly List<KeyValuePair<string, string>> _composePrefixes =
            new List<KeyValuePair<string, string>>();

        // untranslated-JP reporting
        private static readonly ConcurrentDictionary<string, byte> _reported =
            new ConcurrentDictionary<string, byte>(StringComparer.Ordinal);
        private static readonly object _reportLock = new object();
        private static string _reportPath;

        public static int Count => _map.Count + _patterns.Count;

        private static string PluginDir =>
            Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location) ?? ".";

        public static void LoadAll()
        {
            _reportPath = Path.Combine(PluginDir, "untranslated.txt");
            try
            {
                // fresh report per session; the file is a per-run QA artifact
                if (File.Exists(_reportPath)) File.Delete(_reportPath);
            }
            catch { }
            var dir = Path.Combine(PluginDir, "translations");
            if (!Directory.Exists(dir))
            {
                Plugin.Log.LogWarning($"translations folder not found: {dir}");
                return;
            }

            int total = 0, skipped = 0;
            foreach (var file in Directory.EnumerateFiles(dir, "*.json"))
            {
                try
                {
                    var raw = File.ReadAllText(file, Encoding.UTF8);
                    int added = 0, empty = 0, patterns = 0;
                    foreach (var kv in JsonFlat.Parse(raw))
                    {
                        if (string.IsNullOrEmpty(kv.Value)) { empty++; continue; }
                        if (PlaceholderRe.IsMatch(kv.Key))
                        {
                            _patterns.Add(BuildPattern(kv.Key, kv.Value));
                            patterns++;
                        }
                        else
                        {
                            _map[kv.Key] = kv.Value;
                            _normIndex[Normalize(kv.Key)] = kv.Key;
                            added++;
                        }
                    }
                    total += added + patterns;
                    skipped += empty;
                    Plugin.Log.LogInfo(
                        $"loaded {Path.GetFileName(file)}: {added} exact + {patterns} format ({empty} empty)");
                }
                catch (Exception e)
                {
                    Plugin.Log.LogError($"failed to load {file}: {e.Message}");
                }
            }

            _patterns.Sort((a, b) => b.LiteralLen.CompareTo(a.LiteralLen));

            _composePrefixes.Clear();
            foreach (var kv in _map) _composePrefixes.Add(kv);
            _composePrefixes.Sort((a, b) => b.Key.Length.CompareTo(a.Key.Length));

            Plugin.Log.LogInfo($"translations: {total} active, {skipped} empty skipped");
        }

        /// <summary>Log a Japanese string that reached a text component without a
        /// dictionary hit — once per unique string, to log + untranslated.txt.</summary>
        public static void ReportIfUntranslated(string s)
        {
            if (Plugin.CfgLogUntranslated?.Value != true) return;
            if (string.IsNullOrEmpty(s) || !JpRe.IsMatch(s)) return;
            if (_reported.Count >= 2000) return;   // dynamic-value variants could spam forever
            if (!_reported.TryAdd(s, 0)) return;
            var line = s.Replace("\r", "").Replace("\n", "\\n");
            Plugin.Log.LogWarning($"untranslated JP: {line}");
            if (_reportPath == null) return;
            try
            {
                lock (_reportLock)
                {
                    File.AppendAllText(_reportPath, line + Environment.NewLine, Encoding.UTF8);
                }
            }
            catch { /* reporting must never break the game */ }
        }

        public static bool TryGet(string original, out string translated)
            => TryGetInternal(original, 0, out translated);

        private const int MaxRecursion = 24;
        private const int MaxCacheEntries = 40000;   // dynamic text (timers, counters)
                                                     // would otherwise grow these forever

        private static void CacheHit(string key, string value)
        {
            if (_hitCache.Count >= MaxCacheEntries) _hitCache.Clear();
            _hitCache[key] = value;
        }

        private static void CacheMiss(string key)
        {
            if (_missCache.Count >= MaxCacheEntries) _missCache.Clear();
            _missCache[key] = 0;
        }

        private static bool TryGetInternal(string original, int depth, out string translated)
        {
            if (string.IsNullOrEmpty(original)) { translated = null; return false; }
            if (depth > MaxRecursion) { translated = null; return false; }

            if (depth == 0)
            {
                if (_hitCache.TryGetValue(original, out translated)) return true;
                if (_missCache.ContainsKey(original)) { translated = null; return false; }
            }

            // exact match
            if (_map.TryGetValue(original, out translated))
            {
                if (depth == 0) CacheHit(original, translated);
                return true;
            }

            // forgiving match: "\\n" / CRLF / trim differences
            var norm = Normalize(original);
            if (_normIndex.TryGetValue(norm, out var key) && _map.TryGetValue(key, out translated))
            {
                if (depth == 0) CacheHit(original, translated);
                return true;
            }

            // everything below only makes sense for inputs that contain Japanese;
            // gating here keeps unique English strings (most of what the game sets
            // once language is forced) off the O(n*keys) compose walk
            bool hasJp = JpRe.IsMatch(original);

            // format-pattern sweep — most-specific first
            for (int pi = 0; pi < _patterns.Count; pi++)
            {
                var p = _patterns[pi];
                if (p.FirstLiteral.Length > 0 &&
                    !original.StartsWith(p.FirstLiteral, StringComparison.Ordinal)) continue;
                var m = p.Regex.Match(original);
                if (!m.Success) continue;

                var resolved = new string[m.Groups.Count];
                bool ok = true;
                for (int g = 1; g < m.Groups.Count; g++)
                {
                    var v = m.Groups[g].Value;
                    if (v.Length > 0 && JpRe.IsMatch(v))
                    {
                        if (!TryGetInternal(v, depth + 1, out var sub)) { ok = false; break; }
                        resolved[g] = sub;
                    }
                    else
                    {
                        resolved[g] = v;
                    }
                }
                if (!ok) continue;

                translated = Splice(p.Template, resolved, p.Slots);
                if (depth == 0) CacheHit(original, translated);
                return true;
            }

            // compose fallback: concatenation of known pieces
            if (hasJp && depth < MaxRecursion && TryCompose(original, depth, out translated))
            {
                if (depth == 0) CacheHit(original, translated);
                return true;
            }

            if (hasJp && Plugin.CfgFallbackContains?.Value == true)
            {
                foreach (var kv in _map)
                {
                    if (original.Contains(kv.Key))
                    {
                        translated = original.Replace(kv.Key, kv.Value);
                        if (depth == 0) CacheHit(original, translated);
                        return true;
                    }
                }
            }

            if (depth == 0) CacheMiss(original);
            translated = null;
            return false;
        }

        private static string Splice(string template, string[] resolved, int[] slots)
        {
            // slots[g-1] is the placeholder index the regex captured into group g,
            // so "{1}は{0}" -> "{0} is {1}" resolves each {n} to the right capture
            var sb = new StringBuilder(template.Length + 16);
            int idx = 0;
            while (idx < template.Length)
            {
                var pm = PlaceholderRe.Match(template, idx);
                if (!pm.Success || !pm.Groups[0].Success)
                {
                    sb.Append(template, idx, template.Length - idx);
                    break;
                }
                sb.Append(template, idx, pm.Index - idx);
                int n = ExtractSlot(pm.Value);
                int g = -1;
                if (n >= 0 && slots != null)
                {
                    for (int si = 0; si < slots.Length; si++)
                    {
                        if (slots[si] == n) { g = si + 1; break; }
                    }
                }
                if (g >= 1 && g < resolved.Length && resolved[g] != null)
                    sb.Append(resolved[g]);
                else
                    sb.Append(pm.Value);
                idx = pm.Index + pm.Length;
            }
            return sb.ToString();
        }

        /// <summary>Walk the input left-to-right matching known keys/patterns;
        /// handles concatenated outputs no single entry matches in full.
        /// Fails (returns false) when any Japanese would be left untranslated in
        /// the passthrough remainder — a partial splice like "さん？" -> "さHm?"
        /// is worse than showing the original, and a false success would also
        /// suppress the untranslated-string report.</summary>
        private static bool TryCompose(string input, int depth, out string translated)
        {
            translated = null;
            var sb = new StringBuilder(input.Length + 16);
            int pos = 0;
            bool anyTranslated = false;

            while (pos < input.Length)
            {
                bool matched = false;

                for (int ki = 0; ki < _composePrefixes.Count; ki++)
                {
                    var kv = _composePrefixes[ki];
                    if (kv.Key.Length < 2) continue;
                    if (pos + kv.Key.Length > input.Length) continue;
                    if (string.CompareOrdinal(input, pos, kv.Key, 0, kv.Key.Length) != 0) continue;
                    sb.Append(kv.Value);
                    pos += kv.Key.Length;
                    matched = true;
                    anyTranslated = true;
                    break;
                }
                if (matched) continue;

                for (int pi = 0; pi < _patterns.Count; pi++)
                {
                    var p = _patterns[pi];
                    if (p.FirstLiteral.Length > 0)
                    {
                        if (pos + p.FirstLiteral.Length > input.Length) continue;
                        if (string.CompareOrdinal(input, pos, p.FirstLiteral, 0,
                                p.FirstLiteral.Length) != 0) continue;
                    }
                    var m = p.RegexAtStart.Match(input, pos);
                    if (!m.Success || m.Index != pos) continue;

                    var resolved = new string[m.Groups.Count];
                    bool ok = true;
                    for (int g = 1; g < m.Groups.Count; g++)
                    {
                        var v = m.Groups[g].Value;
                        if (v.Length > 0 && JpRe.IsMatch(v))
                        {
                            if (!TryGetInternal(v, depth + 1, out var sub)) { ok = false; break; }
                            resolved[g] = sub;
                        }
                        else
                        {
                            resolved[g] = v;
                        }
                    }
                    if (!ok) continue;

                    sb.Append(Splice(p.Template, resolved, p.Slots));
                    pos += m.Length;
                    matched = true;
                    anyTranslated = true;
                    break;
                }
                if (matched) continue;

                // nothing matched here — pass the char through, but if it's
                // Japanese the composition is incomplete and must fail
                char c = input[pos];
                if ((c >= '぀' && c <= 'ヿ') || (c >= '一' && c <= '鿿'))
                {
                    return false;
                }
                sb.Append(c);
                pos++;
            }

            if (!anyTranslated) return false;
            translated = sb.ToString();
            return true;
        }

        private static int ExtractSlot(string placeholder)
        {
            // "{0}" / "{0:F0}" / "{12,5:N0}" -> 0 / 0 / 12
            int i = 1;
            int n = 0;
            bool any = false;
            while (i < placeholder.Length && placeholder[i] >= '0' && placeholder[i] <= '9')
            {
                n = n * 10 + (placeholder[i] - '0');
                any = true;
                i++;
            }
            return any ? n : -1;
        }

        private static FormatPattern BuildPattern(string jpFormat, string enTemplate)
        {
            var sb = new StringBuilder();
            sb.Append('^');
            int idx = 0;
            int literalLen = 0;
            string firstLiteral = null;
            var slots = new List<int>();
            while (idx < jpFormat.Length)
            {
                var pm = PlaceholderRe.Match(jpFormat, idx);
                if (!pm.Success || !pm.Groups[0].Success)
                {
                    var tail = jpFormat.Substring(idx);
                    sb.Append(Regex.Escape(tail));
                    literalLen += tail.Length;
                    if (firstLiteral == null) firstLiteral = tail;
                    break;
                }
                if (pm.Index > idx)
                {
                    var literal = jpFormat.Substring(idx, pm.Index - idx);
                    if (firstLiteral == null) firstLiteral = literal;
                    sb.Append(Regex.Escape(literal));
                    literalLen += literal.Length;
                }
                else if (firstLiteral == null)
                {
                    firstLiteral = "";
                }
                sb.Append("(.*?)");
                slots.Add(ExtractSlot(pm.Value));   // "{1}は{0}" captures groups for slots 1,0
                idx = pm.Index + pm.Length;
            }
            string body = sb.ToString();
            string anchored = body + "$";
            string atStart = "\\G" + body.Substring(1);
            return new FormatPattern
            {
                Regex = new Regex(anchored,
                    RegexOptions.Compiled | RegexOptions.Singleline | RegexOptions.CultureInvariant),
                RegexAtStart = new Regex(atStart,
                    RegexOptions.Compiled | RegexOptions.Singleline | RegexOptions.CultureInvariant),
                Template = enTemplate,
                FirstLiteral = firstLiteral ?? "",
                LiteralLen = literalLen,
                Slots = slots.ToArray(),
            };
        }

        // collapse literal "\n" / CRLF to \n; trim whitespace
        private static string Normalize(string s)
        {
            if (string.IsNullOrEmpty(s)) return s;
            var sb = new StringBuilder(s.Length);
            for (int i = 0; i < s.Length; i++)
            {
                char c = s[i];
                if (c == '\r') continue;
                if (c == '\\' && i + 1 < s.Length && s[i + 1] == 'n') { sb.Append('\n'); i++; continue; }
                sb.Append(c);
            }
            return sb.ToString().Trim();
        }
    }

    /// <summary>Minimal JSON parser for flat string-string objects.</summary>
    internal static class JsonFlat
    {
        public static IEnumerable<KeyValuePair<string, string>> Parse(string s)
        {
            int i = 0;
            SkipWs(s, ref i);
            Expect(s, ref i, '{');
            SkipWs(s, ref i);
            if (i < s.Length && s[i] == '}') yield break;
            while (i < s.Length)
            {
                SkipWs(s, ref i);
                var key = ReadString(s, ref i);
                SkipWs(s, ref i);
                Expect(s, ref i, ':');
                SkipWs(s, ref i);
                var val = ReadString(s, ref i);
                yield return new KeyValuePair<string, string>(key, val);
                SkipWs(s, ref i);
                if (i < s.Length && s[i] == ',') { i++; continue; }
                if (i < s.Length && s[i] == '}') { i++; yield break; }
                throw new FormatException($"expected ',' or '}}' at offset {i}");
            }
        }

        private static void SkipWs(string s, ref int i)
        {
            while (i < s.Length)
            {
                char c = s[i];
                if (c == ' ' || c == '\t' || c == '\r' || c == '\n') i++;
                else return;
            }
        }

        private static void Expect(string s, ref int i, char c)
        {
            if (i >= s.Length || s[i] != c)
                throw new FormatException($"expected '{c}' at offset {i}");
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
                        case '"': sb.Append('"'); break;
                        case '\\': sb.Append('\\'); break;
                        case '/': sb.Append('/'); break;
                        case 'n': sb.Append('\n'); break;
                        case 'r': sb.Append('\r'); break;
                        case 't': sb.Append('\t'); break;
                        case 'b': sb.Append('\b'); break;
                        case 'f': sb.Append('\f'); break;
                        case 'u':
                            if (i + 4 > s.Length) throw new FormatException("truncated \\u escape");
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
}
