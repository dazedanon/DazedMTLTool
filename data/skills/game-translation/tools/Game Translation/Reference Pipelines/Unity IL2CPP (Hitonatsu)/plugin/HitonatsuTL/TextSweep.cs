using System;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace HitonatsuTL
{
    /// <summary>
    /// Periodic sweep over every live TMP_Text component.
    ///
    /// The setter prefix catches `tmp.text = ...` and the Awake/OnEnable
    /// postfixes catch text Unity deserialized into the m_text backing field.
    /// Neither sees a component that is written once, off-screen, before our
    /// patches are live, or one whose text is assigned through a path that
    /// bypasses the property. This game builds its voice and expression
    /// dropdown labels at runtime out of Addressables address strings, so the
    /// set of strings that can appear is not knowable from the files - a sweep
    /// is the cheap way to be covered anyway rather than merely to believe we
    /// are.
    ///
    /// Cost is one FindObjectsOfType every few seconds over a scene with 50 TMP
    /// components, so it is not worth optimising.
    /// </summary>
    internal sealed class TextSweep : MonoBehaviour
    {
        public TextSweep(IntPtr ptr) : base(ptr) { }

        private float _next;
        private bool _reported;

        private void Start()
        {
            _next = 0f;   // sweep on the first Update, once the scene is up
        }

        private void Update()
        {
            if (Plugin.CfgSweep?.Value != true) return;

            var now = Time.unscaledTime;
            if (now < _next) return;
            _next = now + Math.Max(2f, Plugin.CfgSweepInterval?.Value ?? 5f);

            try
            {
                // Images too. The Image.OnEnable hook only fires on a transition,
                // so anything already enabled when we installed, or re-pointed at
                // a new sprite without a disable/enable cycle, needs picking up
                // here. Cheap: this scene has a few dozen Images.
                var imgs = UnityEngine.Object.FindObjectsOfType<Image>();
                if (imgs != null)
                {
                    for (int i = 0; i < imgs.Length; i++)
                        ImagePatches.Swap(imgs[i]);
                }

                // Report replacements that never matched anything, once, after
                // the first scene has had time to build. A swap that silently
                // never applied looks exactly like one that did.
                if (!_reported && now > 20f)
                {
                    _reported = true;
                    ImagePatches.ReportUnapplied();
                }

                var all = UnityEngine.Object.FindObjectsOfType<TMP_Text>();
                if (all == null) return;
                for (int i = 0; i < all.Length; i++)
                {
                    var t = all[i];
                    if (t == null) continue;
                    var current = t.text;
                    if (string.IsNullOrEmpty(current)) continue;
                    if (TranslationStore.TryGet(current, out var en) && en != current)
                    {
                        t.text = en;
                        if (Plugin.CfgVerbose?.Value == true)
                            Plugin.Log.LogInfo($"TL[sweep]: {current} -> {en}");
                    }
                    else
                    {
                        TranslationStore.ReportIfUntranslated(current, "sweep");
                    }
                }
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"TextSweep failed: {e.Message}");
            }
        }
    }
}
