using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;

namespace LoserLifeATest;

internal static class ExtractedTextStore
{
    private static readonly HashSet<string> KnownTexts = new(StringComparer.Ordinal);
    private static readonly HashSet<string> MissingLogged = new(StringComparer.Ordinal);
    private static List<string> KnownFragments = new();
    private static Dictionary<char, List<string>> KnownFragmentsByFirstChar = new();
    private const int MaxCompositeFragmentLength = 500;

    public static int Count => KnownTexts.Count;

    public static void Load()
    {
        KnownTexts.Clear();
        MissingLogged.Clear();
        KnownFragments = new List<string>();
        KnownFragmentsByFirstChar = new Dictionary<char, List<string>>();

        var pluginDir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        if (string.IsNullOrEmpty(pluginDir))
        {
            Plugin.Log.LogWarning("Could not resolve plugin directory for extracted text list.");
            return;
        }

        var path = Path.Combine(pluginDir, "translations", "known_texts.b64");
        if (!File.Exists(path))
        {
            Plugin.Log.LogWarning($"Extracted text list not found: {path}");
            return;
        }

        foreach (var rawLine in File.ReadLines(path, Encoding.ASCII))
        {
            var line = rawLine.Trim();
            if (line.Length == 0 || line.StartsWith("#", StringComparison.Ordinal))
            {
                continue;
            }

            try
            {
                var text = Encoding.UTF8.GetString(Convert.FromBase64String(line));
                text = Normalize(text);
                if (text.Length > 0)
                {
                    KnownTexts.Add(text);
                }
            }
            catch (Exception ex)
            {
                Plugin.Log.LogWarning($"Failed to read extracted text entry: {ex.Message}");
            }
        }

        var fragments = new HashSet<string>(StringComparer.Ordinal);
        foreach (var text in KnownTexts)
        {
            AddFragment(fragments, text);
            AddFragment(fragments, text.TrimEnd('\uFF0E', '\u3002', '\uFF1A', ':', '\u3001', ',', '.', ' '));
        }

        KnownFragments = fragments
            .OrderByDescending(text => text.Length)
            .ToList();

        KnownFragmentsByFirstChar = KnownFragments
            .GroupBy(text => text[0])
            .ToDictionary(
                group => group.Key,
                group => group.OrderByDescending(text => text.Length).ToList());
    }

    public static bool Contains(string value)
    {
        return value != null && KnownTexts.Contains(Normalize(value));
    }

    public static bool AddRuntimeText(string value)
    {
        var normalized = Normalize(value);
        if (normalized.Length == 0 || !ContainsJapanese(normalized))
        {
            return false;
        }

        if (!KnownTexts.Add(normalized))
        {
            return false;
        }

        AddFragmentToIndex(normalized);
        AddFragmentToIndex(normalized.TrimEnd('\uFF0E', '\u3002', '\uFF1A', ':', '\u3001', ',', '.', ' '));
        return true;
    }

    public static bool TryBuildReplacement(
        string value,
        string marker,
        bool preserveDynamicValues,
        out string replacement,
        out string uncoveredJapanese)
    {
        replacement = null;
        uncoveredJapanese = string.Empty;

        if (value == null)
        {
            return false;
        }

        var normalized = Normalize(value);
        if (KnownTexts.Contains(normalized))
        {
            replacement = marker;
            return true;
        }

        if (Plugin.AllowCompositeExtractedMatch?.Value != true)
        {
            uncoveredJapanese = normalized;
            return false;
        }

        var builder = preserveDynamicValues ? new StringBuilder(normalized.Length) : null;
        var uncovered = new StringBuilder();
        var index = 0;

        while (index < normalized.Length)
        {
            var fragment = FindFragmentAt(normalized, index);
            if (fragment != null)
            {
                builder?.Append(marker);
                index += fragment.Length;
                continue;
            }

            var ch = normalized[index];
            builder?.Append(ch);
            if (IsJapaneseChar(ch))
            {
                uncovered.Append(ch);
            }

            index++;
        }

        uncoveredJapanese = uncovered.ToString();
        if (uncoveredJapanese.Length > 0)
        {
            replacement = null;
            return false;
        }

        replacement = preserveDynamicValues ? builder.ToString() : marker;
        return replacement != normalized;
    }

    public static bool IsCovered(string value, out string uncoveredJapanese)
    {
        uncoveredJapanese = string.Empty;
        if (value == null)
        {
            return false;
        }

        var normalized = Normalize(value);
        if (KnownTexts.Contains(normalized))
        {
            return true;
        }

        if (Plugin.AllowCompositeExtractedMatch?.Value != true)
        {
            uncoveredJapanese = normalized;
            return false;
        }

        var residual = normalized;
        foreach (var fragment in KnownFragments)
        {
            if (residual.Length == 0)
            {
                break;
            }

            residual = residual.Replace(fragment, string.Empty);
        }

        uncoveredJapanese = ExtractJapaneseOnly(residual);
        return uncoveredJapanese.Length == 0;
    }

    public static string Normalize(string value)
    {
        return (value ?? string.Empty)
            .Replace("\r\n", "\n")
            .Replace('\r', '\n')
            .Replace('\u3002', '\uFF0E')
            .Replace("\u200b", string.Empty)
            .Trim();
    }

    public static void LogMissingIfJapanese(string value)
    {
        if (Plugin.LogUnmatchedJapanese?.Value != true)
        {
            return;
        }

        var normalized = Normalize(value);
        if (normalized.Length == 0 || !ContainsJapanese(normalized))
        {
            return;
        }

        if (MissingLogged.Add(normalized))
        {
            Plugin.Log.LogWarning($"Unmatched extracted text: {Truncate(normalized)}");
        }
    }

    public static void LogMissingIfJapanese(string value, string uncoveredJapanese)
    {
        if (Plugin.LogUnmatchedJapanese?.Value != true)
        {
            return;
        }

        var normalized = Normalize(value);
        var uncovered = Normalize(uncoveredJapanese);
        if (normalized.Length == 0 || uncovered.Length == 0 || !ContainsJapanese(uncovered))
        {
            return;
        }

        var key = uncovered + "\n---\n" + normalized;
        if (MissingLogged.Add(key))
        {
            Plugin.Log.LogWarning($"Unmatched extracted text fragment: {Truncate(uncovered)} | full: {Truncate(normalized)}");
        }
    }

    public static bool ContainsJapanese(string value)
    {
        foreach (var ch in value)
        {
            if ((ch >= '\u3040' && ch <= '\u30ff') || (ch >= '\u3400' && ch <= '\u9fff'))
            {
                return true;
            }
        }

        return false;
    }

    private static bool IsJapaneseChar(char ch)
    {
        return (ch >= '\u3040' && ch <= '\u30ff') || (ch >= '\u3400' && ch <= '\u9fff');
    }

    private static void AddFragment(HashSet<string> fragments, string value)
    {
        value = Normalize(value);
        if (value.Length <= MaxCompositeFragmentLength && ContainsJapanese(value) && (value.Length >= 2 || value == "\u500B"))
        {
            fragments.Add(value);
        }
    }

    private static void AddFragmentToIndex(string value)
    {
        value = Normalize(value);
        if (value.Length == 0 ||
            value.Length > MaxCompositeFragmentLength ||
            !ContainsJapanese(value) ||
            (value.Length < 2 && value != "\u500B") ||
            KnownFragments.Contains(value))
        {
            return;
        }

        KnownFragments.Add(value);
        KnownFragments.Sort((left, right) => right.Length.CompareTo(left.Length));

        if (!KnownFragmentsByFirstChar.TryGetValue(value[0], out var fragments))
        {
            fragments = new List<string>();
            KnownFragmentsByFirstChar[value[0]] = fragments;
        }

        fragments.Add(value);
        fragments.Sort((left, right) => right.Length.CompareTo(left.Length));
    }

    private static string FindFragmentAt(string value, int index)
    {
        if (!KnownFragmentsByFirstChar.TryGetValue(value[index], out var fragments))
        {
            return null;
        }

        foreach (var fragment in fragments)
        {
            if (fragment.Length == 0 || index + fragment.Length > value.Length)
            {
                continue;
            }

            if (string.CompareOrdinal(value, index, fragment, 0, fragment.Length) == 0)
            {
                return fragment;
            }
        }

        return null;
    }

    private static string ExtractJapaneseOnly(string value)
    {
        var builder = new StringBuilder(value.Length);
        foreach (var ch in value)
        {
            if ((ch >= '\u3040' && ch <= '\u30ff') || (ch >= '\u3400' && ch <= '\u9fff'))
            {
                builder.Append(ch);
            }
        }

        return builder.ToString();
    }

    private static string Truncate(string value)
    {
        value = value.Replace("\n", "\\n");
        return value.Length <= 120 ? value : value.Substring(0, 117) + "...";
    }
}
