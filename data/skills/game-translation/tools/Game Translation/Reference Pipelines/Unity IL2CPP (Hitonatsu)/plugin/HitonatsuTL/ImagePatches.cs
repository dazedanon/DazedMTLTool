using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using HarmonyLib;
using UnityEngine;
using UnityEngine.UI;

namespace HitonatsuTL
{
    /// <summary>
    /// Replaces sprites whose artwork has Japanese painted into it.
    ///
    /// Only one image in this game is player-facing text: TitleLogo (1400x300,
    /// ひと夏の思い出) on Canvas/Title/Background/Image. Everything else the
    /// image census turned up is world-prop art - a caution label on an electric
    /// fan, wall posters, a towel - which reads as set dressing, not interface.
    ///
    /// Payload is .tex (raw RGBA32), not .png, and that is not a preference.
    /// EVERY ImageConversion.LoadImage overload in this game's interop funnels
    /// into the ReadOnlySpan one:
    ///
    ///     public static bool LoadImage(Texture2D tex, Il2CppStructArray&lt;byte&gt; data)
    ///         =&gt; LoadImage(tex, new Il2CppSystem.ReadOnlySpan&lt;byte&gt;(...), false);
    ///
    /// and the span path needs Il2CppSystem.ReadOnlySpan&lt;byte&gt;.GetPinnableReference,
    /// which this build's corlib has stripped - so it throws `Method not found`
    /// no matter what argument type you hand it, and no matter whether the bytes
    /// were read on the managed or the il2cpp side. Decoding therefore happens at
    /// build time (tools/pack_images.py) and the runtime only uploads pixels
    /// through Texture2D.LoadRawTextureData, which has no span dependency.
    ///
    /// Matching is by the ORIGINAL sprite's name, so dropping a PNG into
    /// images/out/ named after any sprite replaces it with no code change. A
    /// replacement that never matches is reported, because a swap that silently
    /// did not happen looks exactly like one that did.
    /// </summary>
    internal static class ImagePatches
    {
        private const uint Magic = 0x58455448;   // "HTEX" little-endian

        private static readonly Dictionary<string, Sprite> _replacements =
            new Dictionary<string, Sprite>(StringComparer.Ordinal);
        private static readonly HashSet<string> _applied =
            new HashSet<string>(StringComparer.Ordinal);
        private static bool _loaded;

        public static int Count => _replacements.Count;

        public static void LoadAll()
        {
            _loaded = true;
            try
            {
                var dir = Path.Combine(
                    Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location) ?? ".",
                    "images");
                if (!Directory.Exists(dir))
                {
                    Plugin.Log.LogInfo("no images/ folder - image replacement disabled");
                    return;
                }
                foreach (var path in Directory.EnumerateFiles(dir, "*.tex"))
                {
                    var name = Path.GetFileNameWithoutExtension(path);
                    try
                    {
                        var sprite = LoadTex(path, name);
                        if (sprite != null)
                            _replacements[name] = sprite;
                    }
                    catch (Exception e)
                    {
                        Plugin.Log.LogWarning($"failed to load {name}.tex: {e}");
                    }
                }
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"ImagePatches.LoadAll failed: {e.Message}");
            }
        }

        private static Sprite LoadTex(string path, string name)
        {
            var blob = File.ReadAllBytes(path);
            if (blob.Length < 12 || BitConverter.ToUInt32(blob, 0) != Magic)
            {
                Plugin.Log.LogWarning($"{name}.tex: bad header");
                return null;
            }
            int w = BitConverter.ToInt32(blob, 4);
            int h = BitConverter.ToInt32(blob, 8);
            long need = (long)w * h * 4;
            if (w <= 0 || h <= 0 || blob.Length - 12 != need)
            {
                Plugin.Log.LogWarning(
                    $"{name}.tex: header says {w}x{h} ({need} bytes) but the file "
                    + $"carries {blob.Length - 12}");
                return null;
            }

            // mipChain false: a UI sprite is drawn at native size, so mips only
            // cost memory and soften it.
            var tex = new Texture2D(w, h, TextureFormat.RGBA32, false)
            {
                name = name + "_EN",
                wrapMode = TextureWrapMode.Clamp,
                filterMode = FilterMode.Bilinear,
            };

            // Pin the managed buffer and hand LoadRawTextureData a raw pointer.
            // The (IntPtr, int) overload never builds an il2cpp array, so there
            // is nothing for the interop layer to marshal.
            var handle = GCHandle.Alloc(blob, GCHandleType.Pinned);
            try
            {
                var pixels = IntPtr.Add(handle.AddrOfPinnedObject(), 12);
                tex.LoadRawTextureData(pixels, (int)need);
            }
            finally
            {
                handle.Free();
            }
            tex.Apply(false, false);

            var sprite = Sprite.Create(tex, new Rect(0, 0, w, h),
                                       new Vector2(0.5f, 0.5f), 100f);
            sprite.name = name + "_EN";
            UnityEngine.Object.DontDestroyOnLoad(tex);
            UnityEngine.Object.DontDestroyOnLoad(sprite);
            Plugin.Log.LogInfo($"image replacement loaded: {name} ({w}x{h})");
            return sprite;
        }

        public static void Apply(Harmony harmony)
        {
            var target = AccessTools.DeclaredMethod(typeof(Image), "OnEnable");
            if (target == null)
            {
                Plugin.Log.LogWarning("patch target not found, skipping: Image.OnEnable");
                return;
            }
            try
            {
                harmony.Patch(target, postfix: new HarmonyMethod(
                    typeof(ImagePatches), nameof(Image_OnEnable_Postfix)));
                Plugin.Log.LogInfo("patched Image.OnEnable");
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"failed to patch Image.OnEnable: {e.Message}");
            }
        }

        private static void Image_OnEnable_Postfix(Image __instance) => Swap(__instance);

        /// <summary>Swap one Image if its current sprite has a replacement.</summary>
        internal static void Swap(Image img)
        {
            if (!_loaded || _replacements.Count == 0 || img == null) return;
            try
            {
                var current = img.sprite;
                if (current == null) return;
                var name = current.name;
                if (string.IsNullOrEmpty(name)) return;
                if (name.EndsWith("_EN", StringComparison.Ordinal)) return;  // already swapped
                if (!_replacements.TryGetValue(name, out var replacement)) return;
                img.sprite = replacement;
                if (_applied.Add(name))
                    Plugin.Log.LogInfo($"image swapped: {name}");
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"image swap failed: {e.Message}");
            }
        }

        /// <summary>Report replacements that never matched anything on screen.</summary>
        public static void ReportUnapplied()
        {
            foreach (var name in _replacements.Keys)
            {
                if (!_applied.Contains(name))
                    Plugin.Log.LogWarning(
                        $"image replacement '{name}' never matched a sprite - check the "
                        + "filename against the sprite name in the game.");
            }
        }
    }
}
