using System;
using System.Collections.Generic;
using HarmonyLib;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace CoinPussyEnglish
{
    /// <summary>
    /// Layer 2 — the JP->EN dictionary for text baked into scenes and prefabs.
    /// Two coverage layers, because this game sets text both ways:
    ///
    ///   1) Setter prefixes — catch every runtime `tmp.text = "..."`, which is
    ///      how PlayMaker's setTextmeshProUGUIText / UiTextSetText actions write.
    ///      `value` is mutated in-place so the engine only sees English.
    ///
    ///   2) Awake / OnEnable postfixes — catch the 291 labels Unity wrote
    ///      straight into the m_Text / m_text backing field during scene and
    ///      prefab deserialization, which never pass through the setter.
    ///
    /// This runs after every FSM comparison has already happened, so translating
    /// a string that doubles as a StringSwitch key (支配人, バニー, 終了) is safe.
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
                prefix: nameof(UITextSetPrefix), label: "UI.Text.set_text");
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

        // Legacy UI.Text needs the instance so its font can be checked against the
        // translated string before it is assigned.
        private static void UITextSetPrefix(Text __instance, ref string value)
        {
            TryTranslate(ref value);
            EnsureRenderable(__instance, value);
        }

        private static void SetTextPrefix(ref string sourceText) => TryTranslate(ref sourceText);

        // -------- lifecycle postfixes --------

        private static void TmpLifecyclePostfix(TMP_Text __instance) => RefreshTMP(__instance);

        private static void UITextLifecyclePostfix(Text __instance) => RefreshUIText(__instance);

        // -------- helpers --------

        private static readonly HashSet<int> _autoSizedTMP = new HashSet<int>();
        private static readonly HashSet<int> _autoSizedUI = new HashSet<int>();

        // ---- legacy UI.Text font fallback -------------------------------------
        //
        // Legacy UnityEngine.UI.Text draws a glyph its Font does not contain as
        // *nothing* — not tofu, not a box, blank. A non-dynamic Font is baked with
        // only the characters the game shipped, which for a Japanese game means no
        // Latin, so translating one produces an empty button. TMP is unaffected: it
        // has its own atlas and fallback chain.
        //
        // This is invisible unless you compare against the untranslated game, so it
        // is logged once per component either way.
        private static readonly HashSet<int> _fontChecked = new HashSet<int>();
        private static Font _fallbackFont;
        private static bool _fallbackResolved;

        private static readonly System.Text.RegularExpressions.Regex _latinRe =
            new System.Text.RegularExpressions.Regex("[A-Za-z]");

        private static Font ResolveFallbackFont(Font original)
        {
            if (_fallbackResolved) return _fallbackFont;
            _fallbackResolved = true;
            try
            {
                // Prefer a dynamic Font the game already loaded, so the look stays
                // closer to the original than a system font would.
                foreach (var f in Resources.FindObjectsOfTypeAll<Font>())
                {
                    if (f != null && f.dynamic)
                    {
                        _fallbackFont = f;
                        Plugin.Log.LogInfo($"legacy-text fallback font: reusing the game's "
                                           + $"dynamic font '{f.name}'");
                        return _fallbackFont;
                    }
                }
                _fallbackFont = Font.CreateDynamicFontFromOSFont("Arial", 24);
                Plugin.Log.LogInfo("legacy-text fallback font: no dynamic font in the game, "
                                   + "using OS Arial");
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"could not resolve a fallback font: {e.Message}");
            }
            return _fallbackFont;
        }

        /// <summary>Shrink a legacy Text that its own box cannot hold.
        ///
        /// `UnityEngine.UI.Text` with HorizontalOverflow=Wrap and VerticalOverflow=
        /// Truncate draws NOTHING when a single unbreakable word is wider than the
        /// rect — not a clipped word, a blank box. Japanese never trips it because
        /// every glyph is a break opportunity; one long English word does. That is
        /// why a correctly translated "Restart" rendered as an empty button while
        /// さいかいする was fine.
        ///
        /// Best-fit is enabled only for components that actually overflow, so the
        /// rest of the UI keeps its authored size.
        /// </summary>
        private static void FitLegacyText(Text t, string text)
        {
            try
            {
                var rect = t.rectTransform.rect;
                if (rect.width <= 1f) return;
                if (t.preferredWidth <= rect.width && t.preferredHeight <= rect.height) return;
                if (t.resizeTextForBestFit) return;      // already handled
                int max = t.fontSize > 0 ? t.fontSize : 24;
                t.resizeTextForBestFit = true;
                t.resizeTextMinSize = 1;
                t.resizeTextMaxSize = max;
                t.SetAllDirty();
                Plugin.Log.LogInfo($"legacy UI.Text '{t.name}': {Truncate(text)} needs "
                                   + $"{t.preferredWidth:F0}x{t.preferredHeight:F0} in a "
                                   + $"{rect.width:F0}x{rect.height:F0} box — best-fit enabled "
                                   + "(it would otherwise render blank)");
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"FitLegacyText failed: {e.Message}");
            }
        }

        /// <summary>Make sure `text` can actually be drawn by this component's font.
        ///
        /// A dynamic Font rasterises glyphs on demand, and the atlas only holds what
        /// has been requested. Japanese is already in there; the English we swap in
        /// is not. `Text` normally requests its own characters while building the
        /// mesh, but an assignment made from a Harmony postfix during OnEnable can
        /// have its mesh built before the atlas rebuild lands — and a glyph that is
        /// not in the atlas draws as nothing. Requesting up front, then forcing a
        /// rebuild, is what makes the swap visible.
        ///
        /// A non-dynamic font is baked with only the characters the game shipped, so
        /// there Latin can never appear and the font itself has to be replaced.
        /// </summary>
        private static void EnsureRenderable(Text t, string text)
        {
            if (t == null || string.IsNullOrEmpty(text)) return;
            var font = t.font;
            if (font == null || !_latinRe.IsMatch(text)) return;
            try
            {
                if (Plugin.CfgVerbose?.Value == true && _fontChecked.Add(t.GetInstanceID()))
                {
                    Plugin.Log.LogInfo($"legacy UI.Text '{t.name}': font='{font.name}' "
                                       + $"dynamic={font.dynamic}");
                }
                if (font.dynamic)
                {
                    font.RequestCharactersInTexture(text, t.fontSize, t.fontStyle);
                    t.SetAllDirty();
                    FitLegacyText(t, text);
                    return;
                }
                var repl = ResolveFallbackFont(font);
                if (repl != null && !ReferenceEquals(repl, font))
                {
                    t.font = repl;
                    repl.RequestCharactersInTexture(text, t.fontSize, t.fontStyle);
                    t.SetAllDirty();
                }
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"EnsureRenderable failed: {e.Message}");
            }
        }

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
                        Plugin.Log.LogInfo($"TL[init]: {Truncate(current)} -> {Truncate(translated)}");
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

        // Legacy UI.Text assigned from inside OnEnable can render as nothing: the
        // setter marks the graphic dirty, but the component is still mid-OnEnable and
        // not yet registered for a canvas rebuild, so that flag is dropped and the
        // mesh is never regenerated. The Japanese survives because it was baked in at
        // deserialization; our English never gets drawn. TMP is immune — it rebuilds
        // from its own Update loop.
        //
        // So do not assign during OnEnable: queue the component and let the plugin's
        // Update apply it a frame later, when the graphic is live.
        private static readonly List<Text> _pendingUIText = new List<Text>();

        internal static void DrainPending()
        {
            if (_pendingUIText.Count == 0) return;
            List<Text> batch;
            lock (_pendingUIText)
            {
                batch = new List<Text>(_pendingUIText);
                _pendingUIText.Clear();
            }
            foreach (var t in batch)
            {
                if (t == null) continue;
                try
                {
                    var current = t.text;
                    if (string.IsNullOrEmpty(current)) continue;
                    if (TranslationStore.TryGet(current, out var translated)
                        && translated != current)
                    {
                        if (Plugin.CfgVerbose?.Value == true)
                            Plugin.Log.LogInfo($"TL[init]: {Truncate(current)} -> "
                                               + $"{Truncate(translated)}");
                        EnsureRenderable(t, translated);
                        t.text = translated;
                        t.SetAllDirty();
                    }
                    else
                    {
                        TranslationStore.ReportIfUntranslated(current);
                    }
                }
                catch (Exception e)
                {
                    Plugin.Log.LogWarning($"deferred UI.Text refresh failed: {e.Message}");
                }
            }
        }

        private static void RefreshUIText(Text t)
        {
            if (t == null) return;
            try
            {
                EnableAutoSizeUI(t);
                if (string.IsNullOrEmpty(t.text)) return;
                lock (_pendingUIText)
                {
                    _pendingUIText.Add(t);
                }
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"RefreshUIText failed: {e.Message}");
            }
        }

        // Verbose swaps log at Info, not Debug: BepInEx's default disk LogLevels
        // exclude Debug, so a Debug line would make VerboseLogging=true look broken
        // unless the user also edited BepInEx.cfg.
        private static void TryTranslate(ref string value)
        {
            if (string.IsNullOrEmpty(value)) return;
            try
            {
                if (TranslationStore.TryGet(value, out var translated))
                {
                    if (Plugin.CfgVerbose?.Value == true)
                        Plugin.Log.LogInfo($"TL: {Truncate(value)} -> {Truncate(translated)}");
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
