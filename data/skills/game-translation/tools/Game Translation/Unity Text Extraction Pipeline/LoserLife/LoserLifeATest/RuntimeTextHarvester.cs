using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text;
using UnityEngine;
using Object = UnityEngine.Object;

namespace LoserLifeATest;

internal static class RuntimeTextHarvester
{
    private static readonly Encoding Utf8NoBom = new UTF8Encoding(false);
    private static readonly HashSet<string> PersistedTexts = new(StringComparer.Ordinal);
    private static readonly HashSet<int> SeenSkillInstances = new();
    private static string _runtimeLogPath;
    private static float _nextHarvest;
    private static bool _initialized;

    private static readonly string[] SkillDynamicFragments =
    {
        "\u30af\u30fc\u30eb\u30c0\u30a6\u30f3",
        "\u79d2\u3001\u6d88\u8cbb\u9b54\u529b\uff1a",
        "\u79d2\u3001\u6d88\u8cbb\u9b54\u529b:",
        "\u6d88\u8cbb\u9b54\u529b\uff1a",
        "\u6d88\u8cbb\u9b54\u529b:"
    };

    public static void Initialize()
    {
        if (_initialized)
        {
            return;
        }

        _initialized = true;

        foreach (var fragment in SkillDynamicFragments)
        {
            ExtractedTextStore.AddRuntimeText(fragment);
        }

        var pluginDir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        if (string.IsNullOrEmpty(pluginDir))
        {
            Plugin.Log?.LogWarning("Could not resolve plugin directory for runtime text harvest log.");
            return;
        }

        _runtimeLogPath = Path.Combine(pluginDir, "runtime_harvested_texts.tsv");
        LoadPersistedTexts();
    }

    public static bool Tick(bool force = false)
    {
        if (Plugin.HarvestRuntimeTexts?.Value != true)
        {
            return false;
        }

        Initialize();

        var now = Time.unscaledTime;
        if (!force && now < _nextHarvest)
        {
            return false;
        }

        var interval = Math.Max(2.0f, Plugin.RuntimeHarvestIntervalSeconds?.Value ?? 5.0f);
        _nextHarvest = now + interval;

        var added = 0;
        added += HarvestActiveSkills();
        added += HarvestSkillSlots();
        added += HarvestUiSkills();
        added += HarvestNotPermitSkills();

        if (Plugin.Verbose?.Value == true && added > 0)
        {
            Plugin.Log.LogDebug($"Runtime text harvest learned {added} strings");
        }

        return added > 0;
    }

    public static bool HarvestFromUiSkill(global::UI_Skill uiSkill)
    {
        if (Plugin.HarvestRuntimeTexts?.Value != true || uiSkill == null)
        {
            return false;
        }

        Initialize();
        var added = 0;
        added += HarvestSkill(uiSkill.selectSkill, "UI_Skill.selectSkill");
        added += HarvestSkill(uiSkill.draggingSkill, "UI_Skill.draggingSkill");
        return added > 0;
    }

    public static bool HarvestFromSkillSlot(global::SkillSlotTemplate slot)
    {
        if (Plugin.HarvestRuntimeTexts?.Value != true || slot == null)
        {
            return false;
        }

        Initialize();
        return HarvestSkill(slot.skill, "SkillSlotTemplate.skill") > 0;
    }

    private static int HarvestActiveSkills()
    {
        var added = 0;

        try
        {
            foreach (var skill in Object.FindObjectsOfType<global::Skill>())
            {
                added += HarvestSkill(skill, "Skill");
            }
        }
        catch (Exception ex)
        {
            Plugin.Log?.LogWarning($"Runtime skill harvest failed: {ex.Message}");
        }

        return added;
    }

    private static int HarvestSkillSlots()
    {
        var added = 0;

        try
        {
            foreach (var slot in Object.FindObjectsOfType<global::SkillSlotTemplate>())
            {
                if (slot != null)
                {
                    added += HarvestSkill(slot.skill, "SkillSlotTemplate.skill");
                }
            }
        }
        catch (Exception ex)
        {
            Plugin.Log?.LogWarning($"Runtime skill slot harvest failed: {ex.Message}");
        }

        return added;
    }

    private static int HarvestUiSkills()
    {
        var added = 0;

        try
        {
            foreach (var uiSkill in Object.FindObjectsOfType<global::UI_Skill>())
            {
                if (uiSkill == null)
                {
                    continue;
                }

                added += HarvestSkill(uiSkill.selectSkill, "UI_Skill.selectSkill");
                added += HarvestSkill(uiSkill.draggingSkill, "UI_Skill.draggingSkill");
            }
        }
        catch (Exception ex)
        {
            Plugin.Log?.LogWarning($"Runtime UI skill harvest failed: {ex.Message}");
        }

        return added;
    }

    private static int HarvestNotPermitSkills()
    {
        var added = 0;

        try
        {
            foreach (var notPermitSkill in Object.FindObjectsOfType<global::NotPermitSkill>())
            {
                if (notPermitSkill != null)
                {
                    added += AddText(notPermitSkill.notPermitMessage, "NotPermitSkill.notPermitMessage");
                }
            }
        }
        catch (Exception ex)
        {
            Plugin.Log?.LogWarning($"Runtime not-permit skill harvest failed: {ex.Message}");
        }

        return added;
    }

    private static int HarvestSkill(global::Skill skill, string source)
    {
        if (skill == null)
        {
            return 0;
        }

        var added = 0;
        var instanceId = SafeInstanceId(skill);

        if (instanceId == 0 || SeenSkillInstances.Add(instanceId))
        {
            added += AddText(skill.name, source + ".name");
            added += AddText(skill.tip, source + ".tip");
        }
        else
        {
            added += AddText(skill.name, source + ".name");
            added += AddText(skill.tip, source + ".tip");
        }

        return added;
    }

    private static int AddText(string value, string source)
    {
        var normalized = ExtractedTextStore.Normalize(value);
        if (normalized.Length == 0 || !ExtractedTextStore.ContainsJapanese(normalized))
        {
            return 0;
        }

        if (ExtractedTextStore.Contains(normalized) || !ExtractedTextStore.AddRuntimeText(normalized))
        {
            return 0;
        }

        PersistIfNeeded(source, normalized);
        TextRuntime.ClearReplacementCaches();
        TextRuntime.RequestSweep();
        return 1;
    }

    private static int SafeInstanceId(Object value)
    {
        try
        {
            return value.GetInstanceID();
        }
        catch
        {
            return 0;
        }
    }

    private static void LoadPersistedTexts()
    {
        if (string.IsNullOrEmpty(_runtimeLogPath) || !File.Exists(_runtimeLogPath))
        {
            return;
        }

        try
        {
            foreach (var line in File.ReadLines(_runtimeLogPath, Utf8NoBom))
            {
                var parts = line.Split('\t');
                if (parts.Length >= 3)
                {
                    PersistedTexts.Add(Unescape(parts[2]));
                }
            }
        }
        catch (Exception ex)
        {
            Plugin.Log?.LogWarning($"Could not read runtime harvest log: {ex.Message}");
        }
    }

    private static void PersistIfNeeded(string source, string text)
    {
        if (Plugin.WriteRuntimeHarvestLog?.Value != true ||
            string.IsNullOrEmpty(_runtimeLogPath) ||
            !PersistedTexts.Add(text))
        {
            return;
        }

        try
        {
            var line = string.Concat(
                DateTimeOffset.Now.ToString("O"),
                "\t",
                Escape(source),
                "\t",
                Escape(text),
                Environment.NewLine);
            File.AppendAllText(_runtimeLogPath, line, Utf8NoBom);
        }
        catch (Exception ex)
        {
            Plugin.Log?.LogWarning($"Could not append runtime harvest log: {ex.Message}");
        }
    }

    private static string Escape(string value)
    {
        return (value ?? string.Empty)
            .Replace("\\", "\\\\")
            .Replace("\r", "\\r")
            .Replace("\n", "\\n")
            .Replace("\t", "\\t");
    }

    private static string Unescape(string value)
    {
        return (value ?? string.Empty)
            .Replace("\\t", "\t")
            .Replace("\\n", "\n")
            .Replace("\\r", "\r")
            .Replace("\\\\", "\\");
    }
}
