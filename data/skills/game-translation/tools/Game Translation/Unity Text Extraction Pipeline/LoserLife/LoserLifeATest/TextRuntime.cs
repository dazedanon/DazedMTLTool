using System;
using System.Collections.Generic;
using System.Text;
using TMPro;
using UnityEngine;
using UnityEngine.UI;
using Object = UnityEngine.Object;

namespace LoserLifeATest;

internal static class TextRuntime
{
    private const int MaxCacheEntries = 8192;
    private static readonly Dictionary<string, string> ReplacementCache = new(StringComparer.Ordinal);
    private static readonly HashSet<string> NoReplacementCache = new(StringComparer.Ordinal);
    private static readonly Dictionary<int, string> LastTextByInstance = new();
    private static bool _sweepRequested;

    public static string CurrentReplacement => Plugin.Replacement?.Value ?? "A";

    public static void Replace(ref string value)
    {
        if (!TryBuildReplacement(value, out var replacement))
        {
            return;
        }

        value = replacement;
    }

    public static bool ReplaceTMP(TMP_Text text)
    {
        if (text == null)
        {
            return false;
        }

        try
        {
            var current = text.text;
            var id = text.GetInstanceID();
            if (LastTextByInstance.TryGetValue(id, out var lastSeen) && lastSeen == current)
            {
                return false;
            }

            if (!TryBuildReplacement(current, out var replacement))
            {
                LastTextByInstance[id] = current;
                return false;
            }

            text.text = replacement;
            LastTextByInstance[id] = replacement;
            return true;
        }
        catch (Exception ex)
        {
            Plugin.Log?.LogWarning($"TMP replace failed: {ex.Message}");
            return false;
        }
    }

    public static bool ReplaceUIText(Text text)
    {
        if (text == null)
        {
            return false;
        }

        try
        {
            var current = text.text;
            var id = text.GetInstanceID();
            if (LastTextByInstance.TryGetValue(id, out var lastSeen) && lastSeen == current)
            {
                return false;
            }

            if (!TryBuildReplacement(current, out var replacement))
            {
                LastTextByInstance[id] = current;
                return false;
            }

            text.text = replacement;
            LastTextByInstance[id] = replacement;
            return true;
        }
        catch (Exception ex)
        {
            Plugin.Log?.LogWarning($"UI.Text replace failed: {ex.Message}");
            return false;
        }
    }

    public static void SweepActiveText()
    {
        var tmpChanged = 0;
        var uiChanged = 0;

        try
        {
            foreach (var text in Object.FindObjectsOfType<TMP_Text>())
            {
                if (ReplaceTMP(text))
                {
                    tmpChanged++;
                }
            }
        }
        catch (Exception ex)
        {
            Plugin.Log?.LogWarning($"TMP sweep failed: {ex.Message}");
        }

        try
        {
            foreach (var text in Object.FindObjectsOfType<Text>())
            {
                if (ReplaceUIText(text))
                {
                    uiChanged++;
                }
            }
        }
        catch (Exception ex)
        {
            Plugin.Log?.LogWarning($"UI.Text sweep failed: {ex.Message}");
        }

        if (Plugin.Verbose?.Value == true && (tmpChanged > 0 || uiChanged > 0))
        {
            Plugin.Log.LogDebug($"Sweep replaced TMP={tmpChanged}, UI.Text={uiChanged}");
        }
    }

    public static void ClearComponentCache()
    {
        LastTextByInstance.Clear();
    }

    public static void ClearReplacementCaches()
    {
        ReplacementCache.Clear();
        NoReplacementCache.Clear();
        LastTextByInstance.Clear();
    }

    public static void RequestSweep()
    {
        _sweepRequested = true;
    }

    public static bool ConsumeSweepRequest()
    {
        if (!_sweepRequested)
        {
            return false;
        }

        _sweepRequested = false;
        return true;
    }

    private static bool TryBuildReplacement(string value, out string replacement)
    {
        replacement = null;

        if (value == CurrentReplacement)
        {
            return false;
        }

        if (string.IsNullOrEmpty(value) && Plugin.ReplaceEmptyText?.Value != true)
        {
            return false;
        }

        if (!ExtractedTextStore.ContainsJapanese(value))
        {
            return false;
        }

        var cacheKey = BuildCacheKey(value);
        if (ReplacementCache.TryGetValue(cacheKey, out replacement))
        {
            return true;
        }

        if (NoReplacementCache.Contains(cacheKey))
        {
            replacement = null;
            return false;
        }

        if (Plugin.RequireExtractedMatch?.Value == true)
        {
            if (!ExtractedTextStore.TryBuildReplacement(
                    value,
                    CurrentReplacement,
                    Plugin.PreserveDynamicValues?.Value == true,
                    out replacement,
                    out var uncoveredJapanese))
            {
                ExtractedTextStore.LogMissingIfJapanese(value, uncoveredJapanese);
                CacheNoReplacement(cacheKey);
                return false;
            }

            if (replacement == value)
            {
                CacheNoReplacement(cacheKey);
                return false;
            }

            CacheReplacement(cacheKey, replacement);
            return true;
        }

        replacement = Plugin.PreserveDynamicValues?.Value == true
            ? ReplaceJapaneseRuns(value)
            : CurrentReplacement;

        if (replacement == value)
        {
            CacheNoReplacement(cacheKey);
            return false;
        }

        CacheReplacement(cacheKey, replacement);
        return true;
    }

    private static string BuildCacheKey(string value)
    {
        return string.Concat(
            CurrentReplacement,
            "\u001e",
            Plugin.RequireExtractedMatch?.Value == true ? "1" : "0",
            Plugin.AllowCompositeExtractedMatch?.Value == true ? "1" : "0",
            Plugin.PreserveDynamicValues?.Value == true ? "1" : "0",
            "\u001f",
            value);
    }

    private static void CacheReplacement(string key, string value)
    {
        TrimCachesIfNeeded();
        ReplacementCache[key] = value;
    }

    private static void CacheNoReplacement(string key)
    {
        TrimCachesIfNeeded();
        NoReplacementCache.Add(key);
    }

    private static void TrimCachesIfNeeded()
    {
        if (ReplacementCache.Count + NoReplacementCache.Count < MaxCacheEntries)
        {
            return;
        }

        ReplacementCache.Clear();
        NoReplacementCache.Clear();
    }

    private static string ReplaceJapaneseRuns(string value)
    {
        var marker = CurrentReplacement;
        var builder = new StringBuilder(value.Length);
        var inJapaneseRun = false;

        foreach (var ch in value)
        {
            if (IsJapanese(ch))
            {
                if (!inJapaneseRun)
                {
                    builder.Append(marker);
                    inJapaneseRun = true;
                }

                continue;
            }

            inJapaneseRun = false;
            builder.Append(ch);
        }

        return builder.ToString();
    }

    private static bool IsJapanese(char ch)
    {
        return (ch >= '\u3040' && ch <= '\u30ff') || (ch >= '\u3400' && ch <= '\u9fff');
    }
}
