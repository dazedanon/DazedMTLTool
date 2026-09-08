using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;

namespace SheepClickerTL
{
    /// <summary>
    /// Loads JSON translation files at startup and serves runtime lookups.
    /// JSON shape: { "<japanese>": "<english>" }. Empty values are skipped.
    /// Uses a no-allocation hand-rolled JSON parser (BepInEx IL2CPP plugins
    /// don't have System.Text.Json by default and we want to keep deps tiny).
    /// </summary>
    internal static class TranslationStore
    {
        private static readonly ConcurrentDictionary<string, string> _map =
            new ConcurrentDictionary<string, string>(StringComparer.Ordinal);

        // cache of normalized -> original key, used for forgiving newline matches
        private static readonly ConcurrentDictionary<string, string> _normIndex =
            new ConcurrentDictionary<string, string>(StringComparer.Ordinal);

        // Format-string patterns. JP "信仰値 {0}/{1}" -> EN "Faith {0}/{1}".
        // We compile JP into a regex, capturing the runtime values that fill
        // the placeholders, then splat them into the EN template. This is
        // immune to whether the game built the string via String.Format,
        // string interpolation, StringBuilder, or +-concat.
        private sealed class FormatPattern
        {
            public Regex Regex;           // ^literal(.*?)literal$ — full input match
            public Regex RegexAtStart;    // ^literal(.*?)literal — matches a prefix chunk
            public string Template;       // EN template with {0},{1},...
            public string FirstLiteral;   // first literal chunk, used as a fast skip
            public int LiteralLen;        // total literal-anchor length, used to sort by specificity
        }
        private static readonly List<FormatPattern> _patterns = new List<FormatPattern>();
        private static readonly Regex PlaceholderRe = new Regex(
            @"\{\d+(?::[^{}]*)?(?:,-?\d+)?\}", RegexOptions.Compiled);

        // captured runtime values can't contain Japanese — that's the
        // signature of a pattern over-matching. e.g. "{0}円" run against
        // "-資産　500円" captures "-資産　500"; rejecting it lets a more
        // specific pattern (or an exact entry) win.
        private static readonly Regex JpRe = new Regex(
            @"[぀-ゟ゠-ヿ一-鿿]", RegexOptions.Compiled);

        // hot-path cache: any string we've previously translated (success or
        // miss). Avoids re-running regex sweeps on the same text every frame.
        private static readonly ConcurrentDictionary<string, string> _hitCache =
            new ConcurrentDictionary<string, string>(StringComparer.Ordinal);
        private static readonly ConcurrentDictionary<string, byte> _missCache =
            new ConcurrentDictionary<string, byte>(StringComparer.Ordinal);

        // exact-match keys sorted by length descending. Used by the compose
        // fallback to find the longest known JP prefix of an input.
        private static readonly List<KeyValuePair<string, string>> _composePrefixes =
            new List<KeyValuePair<string, string>>();

        public static int Count => _map.Count + _patterns.Count;

        public static void LoadAll()
        {
            var dir = Path.Combine(
                Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location) ?? ".",
                "translations");
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
                    var pairs = JsonFlat.Parse(raw);
                    int added = 0, empty = 0, patterns = 0;
                    foreach (var kv in pairs)
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

            // sort patterns by literal-anchor length, descending. Most
            // specific patterns get tried first, so "信者 {0}/{1}  費用:{2}"
            // (long anchor) wins over "{0}円" (short anchor) when both could
            // match the same input.
            _patterns.Sort((a, b) => b.LiteralLen.CompareTo(a.LiteralLen));

            // build the compose-prefix list: every exact-match key,
            // sorted by length descending so longer prefixes win.
            _composePrefixes.Clear();
            foreach (var kv in _map) _composePrefixes.Add(kv);
            _composePrefixes.Sort((a, b) => b.Key.Length.CompareTo(a.Key.Length));

            Plugin.Log.LogInfo($"translations: {total} active, {skipped} pending");
        }

        public static bool TryGet(string original, out string translated)
            => TryGetInternal(original, 0, out translated);

        // each "line" of a concatenated multi-line panel adds one level of
        // compose recursion, plus per-capture translations add a few more;
        // 24 is comfortably above what the longest in-game panel needs
        private const int MaxRecursion = 24;

        private static bool TryGetInternal(string original, int depth, out string translated)
        {
            if (string.IsNullOrEmpty(original)) { translated = null; return false; }
            if (depth > MaxRecursion) { translated = null; return false; }

            // hot caches (only consult for top-level lookups so recursive
            // calls don't permanently poison the cache with partial state)
            if (depth == 0)
            {
                if (_hitCache.TryGetValue(original, out translated)) return true;
                if (_missCache.ContainsKey(original)) { translated = null; return false; }
            }

            // exact match
            if (_map.TryGetValue(original, out translated))
            {
                if (depth == 0) _hitCache[original] = translated;
                return true;
            }

            // forgiving match: "\\n" / CRLF differences
            var norm = Normalize(original);
            if (_normIndex.TryGetValue(norm, out var key) && _map.TryGetValue(key, out translated))
            {
                if (depth == 0) _hitCache[original] = translated;
                return true;
            }

            // format-pattern sweep — patterns are sorted most-specific first
            for (int pi = 0; pi < _patterns.Count; pi++)
            {
                var p = _patterns[pi];
                if (p.FirstLiteral.Length > 0 &&
                    !original.StartsWith(p.FirstLiteral, StringComparison.Ordinal)) continue;
                var m = p.Regex.Match(original);
                if (!m.Success) continue;

                // resolve each capture: if it contains JP, try to recursively
                // translate it. Failure to translate a JP capture means this
                // pattern is over-matching and we should try the next one.
                var resolved = new string[m.Groups.Count];
                bool ok = true;
                for (int g = 1; g < m.Groups.Count; g++)
                {
                    var v = m.Groups[g].Value;
                    if (v.Length > 0 && JpRe.IsMatch(v))
                    {
                        if (!TryGetInternal(v, depth + 1, out var sub))
                        {
                            ok = false;
                            break;
                        }
                        resolved[g] = sub;
                    }
                    else
                    {
                        resolved[g] = v;
                    }
                }
                if (!ok) continue;

                // splice resolved captures into EN template
                var sb = new StringBuilder(p.Template.Length + 16);
                int idx = 0;
                while (idx < p.Template.Length)
                {
                    var pm = PlaceholderRe.Match(p.Template, idx);
                    if (!pm.Success || !pm.Groups[0].Success)
                    {
                        sb.Append(p.Template, idx, p.Template.Length - idx);
                        break;
                    }
                    sb.Append(p.Template, idx, pm.Index - idx);
                    int n = ExtractSlot(pm.Value);
                    if (n >= 0 && n + 1 < resolved.Length && resolved[n + 1] != null)
                        sb.Append(resolved[n + 1]);
                    else
                        sb.Append(pm.Value);
                    idx = pm.Index + pm.Length;
                }
                translated = sb.ToString();
                if (depth == 0) _hitCache[original] = translated;
                return true;
            }

            // compose fallback: input is the concatenation of a known prefix
            // (exact-match key) and a translatable remainder. Catches the
            // game's `tmp.text = "-資産　" + value + "円"` style where each
            // piece lives as a separate ldstr but the runtime concat never
            // matches any single pattern.
            if (depth < MaxRecursion && TryCompose(original, depth, out translated))
            {
                if (depth == 0) _hitCache[original] = translated;
                return true;
            }

            if (Plugin.CfgFallbackContains?.Value == true)
            {
                foreach (var kv in _map)
                {
                    if (original.Contains(kv.Key))
                    {
                        translated = original.Replace(kv.Key, kv.Value);
                        if (depth == 0) _hitCache[original] = translated;
                        return true;
                    }
                }
            }

            if (depth == 0) _missCache[original] = 0;
            translated = null;
            return false;
        }

        /// <summary>
        /// Walk the input left-to-right. At each position try the longest
        /// matching exact key, then the most-specific matching format
        /// pattern, then advance one character if neither hit.
        ///
        /// This handles concatenated outputs that no single pattern matches
        /// in full, like the floating gain popup
        ///   "<color=green>+112円</color> <color=#FFD700>信仰+3</color>"
        /// which is two separate patterns plus literal " " between.
        /// </summary>
        private static bool TryCompose(string input, int depth, out string translated)
        {
            translated = null;
            var sb = new StringBuilder(input.Length + 16);
            int pos = 0;
            bool anyTranslated = false;

            while (pos < input.Length)
            {
                bool matched = false;

                // 1) try exact keys at pos (longest first)
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

                // 2) try format patterns anchored at pos
                for (int pi = 0; pi < _patterns.Count; pi++)
                {
                    var p = _patterns[pi];
                    // fast skip via FirstLiteral
                    if (p.FirstLiteral.Length > 0)
                    {
                        if (pos + p.FirstLiteral.Length > input.Length) continue;
                        if (string.CompareOrdinal(input, pos, p.FirstLiteral, 0,
                                p.FirstLiteral.Length) != 0) continue;
                    }
                    var m = p.RegexAtStart.Match(input, pos);
                    if (!m.Success || m.Index != pos) continue;

                    // resolve captures (recursively translate JP captures)
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

                    // splice resolved captures into EN template
                    int idx = 0;
                    while (idx < p.Template.Length)
                    {
                        var pm = PlaceholderRe.Match(p.Template, idx);
                        if (!pm.Success || !pm.Groups[0].Success)
                        {
                            sb.Append(p.Template, idx, p.Template.Length - idx);
                            break;
                        }
                        sb.Append(p.Template, idx, pm.Index - idx);
                        int n = ExtractSlot(pm.Value);
                        if (n >= 0 && n + 1 < resolved.Length && resolved[n + 1] != null)
                            sb.Append(resolved[n + 1]);
                        else
                            sb.Append(pm.Value);
                        idx = pm.Index + pm.Length;
                    }
                    pos += m.Length;
                    matched = true;
                    anyTranslated = true;
                    break;
                }
                if (matched) continue;

                // nothing matched at this position — pass through one char
                sb.Append(input[pos]);
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
            // Scan jpFormat, emit either escaped literal or capture group per slot.
            var sb = new StringBuilder();
            sb.Append('^');
            int idx = 0;
            int literalLen = 0;
            string firstLiteral = null;
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
                    firstLiteral = ""; // placeholder is at the start
                }
                sb.Append("(.*?)");
                idx = pm.Index + pm.Length;
            }
            // Two variants:
            //   Regex        — anchored ^...$  (full-input match)
            //   RegexAtStart — \G...           (anchor to the *search start*
            //                                   position; ^ would only match
            //                                   absolute index 0, breaking
            //                                   walker calls at any pos > 0)
            string body = sb.ToString();              // currently "^literal(.*?)..."
            string anchored = body + "$";             // ^...$ for full-input
            string atStart  = "\\G" + body.Substring(1); // \G... for walker
            return new FormatPattern
            {
                Regex = new Regex(anchored,
                    RegexOptions.Compiled | RegexOptions.Singleline | RegexOptions.CultureInvariant),
                RegexAtStart = new Regex(atStart,
                    RegexOptions.Compiled | RegexOptions.Singleline | RegexOptions.CultureInvariant),
                Template = enTemplate,
                FirstLiteral = firstLiteral ?? "",
                LiteralLen = literalLen,
            };
        }

        // collapse "\\n" / CRLF to single \n; trim whitespace
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

    /// <summary>
    /// Minimal JSON parser for flat string-string objects (our translation files).
    /// Avoids pulling in Newtonsoft / System.Text.Json into an IL2CPP plugin.
    /// </summary>
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
