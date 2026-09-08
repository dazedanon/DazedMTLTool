using System;
using System.Collections.Generic;
using HarmonyLib;
using TMPro;
using UnityEngine.UI;

namespace NTRSoccerEnglish
{
    /// <summary>
    /// Dictionary safety net, ported from SheepClickerTL. Two coverage layers:
    ///
    ///   1) Setter prefixes — catch every runtime `tmp.text = "..."` from
    ///      game code. `value` is mutated in-place so the engine only ever
    ///      sees the translated string.
    ///
    ///   2) Awake / OnEnable postfixes — catch text Unity wrote directly into
    ///      the m_text backing field during scene/prefab deserialization
    ///      (static labels that never pass through the setter).
    ///
    /// With ForceEnglishLanguage active the dialogue system already emits
    /// English, so these hooks mostly idle; they exist to catch anything that
    /// bypasses the localization framework, and to report leftovers.
    /// </summary>
    internal static class TextPatches
    {
        public static int Apply(Harmony harmony)
        {
            int n = 0;
            n += TryPatch(harmony, AccessTools.PropertySetter(typeof(TMP_Text), "text"),
                prefix: nameof(String0Prefix), label: "TMP_Text.set_text");
            n += TryPatch(harmony,
                AccessTools.Method(typeof(TMP_Text), "SetText",
                    new[] { typeof(string), typeof(bool) }),
                prefix: nameof(SetTextPrefix), label: "TMP_Text.SetText(string,bool)");
            n += TryPatch(harmony, AccessTools.Method(typeof(TextMeshProUGUI), "Awake"),
                postfix: nameof(TmpLifecyclePostfix), label: "TextMeshProUGUI.Awake");
            n += TryPatch(harmony, AccessTools.Method(typeof(TextMeshProUGUI), "OnEnable"),
                postfix: nameof(TmpLifecyclePostfix), label: "TextMeshProUGUI.OnEnable");
            n += TryPatch(harmony, AccessTools.Method(typeof(TextMeshPro), "Awake"),
                postfix: nameof(TmpLifecyclePostfix), label: "TextMeshPro.Awake");
            n += TryPatch(harmony, AccessTools.Method(typeof(TextMeshPro), "OnEnable"),
                postfix: nameof(TmpLifecyclePostfix), label: "TextMeshPro.OnEnable");
            n += TryPatch(harmony, AccessTools.PropertySetter(typeof(Text), "text"),
                prefix: nameof(String0Prefix), label: "UI.Text.set_text");
            n += TryPatch(harmony, AccessTools.Method(typeof(Text), "OnEnable"),
                postfix: nameof(UITextLifecyclePostfix), label: "UI.Text.OnEnable");
            return n;
        }

        private static int TryPatch(Harmony harmony, System.Reflection.MethodBase target,
            string prefix = null, string postfix = null, string label = "")
        {
            if (target == null)
            {
                Plugin.Log.LogWarning($"patch target not found: {label}");
                return 0;
            }
            try
            {
                harmony.Patch(target,
                    prefix: prefix == null ? null : new HarmonyMethod(typeof(TextPatches), prefix),
                    postfix: postfix == null ? null : new HarmonyMethod(typeof(TextPatches), postfix));
                return 1;
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"failed to patch {label}: {e.Message}");
                return 0;
            }
        }

        // -------- prefixes --------

        private static void String0Prefix(ref string value) => TryTranslate(ref value);

        private static void SetTextPrefix(ref string sourceText) => TryTranslate(ref sourceText);

        // -------- lifecycle postfixes --------

        private static void TmpLifecyclePostfix(TMP_Text __instance) => RefreshTMP(__instance);

        private static void UITextLifecyclePostfix(Text __instance) => RefreshUIText(__instance);

        // -------- helpers --------

        private static readonly HashSet<int> _autoSizedTMP = new HashSet<int>();
        private static readonly HashSet<int> _autoSizedUI = new HashSet<int>();

        private static void EnableAutoSizeTMP(TMP_Text t)
        {
            if (t == null || Plugin.CfgAutoSize?.Value != true) return;
            int id;
            try { id = t.GetInstanceID(); } catch { return; }
            if (!_autoSizedTMP.Add(id)) return;
            try
            {
                float originalSize = t.fontSize;
                if (originalSize <= 0) originalSize = 24f;
                t.enableAutoSizing = true;
                t.fontSizeMin = 6f;
                t.fontSizeMax = originalSize;
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"EnableAutoSizeTMP failed: {e.Message}");
            }
        }

        private static void EnableAutoSizeUI(Text t)
        {
            if (t == null || Plugin.CfgAutoSize?.Value != true) return;
            int id;
            try { id = t.GetInstanceID(); } catch { return; }
            if (!_autoSizedUI.Add(id)) return;
            try
            {
                int originalSize = t.fontSize;
                if (originalSize <= 0) originalSize = 24;
                t.resizeTextForBestFit = true;
                t.resizeTextMinSize = 6;
                t.resizeTextMaxSize = originalSize;
                t.SetVerticesDirty();
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"EnableAutoSizeUI failed: {e.Message}");
            }
        }

        private static void RefreshTMP(TMP_Text t)
        {
            if (t == null) return;
            try
            {
                EnableAutoSizeTMP(t);
                var current = t.text;
                if (string.IsNullOrEmpty(current)) return;
                if (TranslationStore.TryGet(current, out var translated) && translated != current)
                {
                    if (Plugin.CfgVerbose?.Value == true)
                        Plugin.Log.LogDebug($"TL[init]: {Truncate(current)} -> {Truncate(translated)}");
                    t.text = translated;   // goes through the setter prefix; EN misses pass through
                }
                else
                {
                    TranslationStore.ReportIfUntranslated(current);
                }
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"RefreshTMP failed: {e.Message}");
            }
        }

        private static void RefreshUIText(Text t)
        {
            if (t == null) return;
            try
            {
                EnableAutoSizeUI(t);
                var current = t.text;
                if (string.IsNullOrEmpty(current)) return;
                if (TranslationStore.TryGet(current, out var translated) && translated != current)
                {
                    if (Plugin.CfgVerbose?.Value == true)
                        Plugin.Log.LogDebug($"TL[init]: {Truncate(current)} -> {Truncate(translated)}");
                    t.text = translated;
                }
                else
                {
                    TranslationStore.ReportIfUntranslated(current);
                }
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"RefreshUIText failed: {e.Message}");
            }
        }

        private static void TryTranslate(ref string value)
        {
            if (string.IsNullOrEmpty(value)) return;
            try
            {
                if (TranslationStore.TryGet(value, out var translated))
                {
                    if (Plugin.CfgVerbose?.Value == true)
                        Plugin.Log.LogDebug($"TL: {Truncate(value)} -> {Truncate(translated)}");
                    value = translated;
                }
                else
                {
                    TranslationStore.ReportIfUntranslated(value);
                }
            }
            catch (Exception e)
            {
                // a throw here would escape into the game's text setter
                Plugin.Log.LogWarning($"TryTranslate failed: {e.Message}");
            }
        }

        private static string Truncate(string s)
        {
            if (s == null) return "<null>";
            return s.Length <= 60 ? s : s.Substring(0, 57) + "...";
        }
    }
}
