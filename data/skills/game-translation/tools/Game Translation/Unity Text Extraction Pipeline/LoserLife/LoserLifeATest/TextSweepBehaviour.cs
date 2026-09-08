using System;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace LoserLifeATest;

internal sealed class TextSweepBehaviour : MonoBehaviour
{
    private float _nextSweep;
    private string _lastSceneName;

    public TextSweepBehaviour(IntPtr pointer) : base(pointer)
    {
    }

    private void Start()
    {
        _lastSceneName = GetSceneName();
        _nextSweep = Time.unscaledTime + Math.Max(5.0f, Plugin.SweepIntervalSeconds?.Value ?? 15.0f);
        RuntimeTextHarvester.Tick(force: true);
        TextRuntime.SweepActiveText();
    }

    private void Update()
    {
        RuntimeTextHarvester.Tick();
        if (TextRuntime.ConsumeSweepRequest() && Plugin.EnableSweeper?.Value == true)
        {
            TextRuntime.SweepActiveText();
        }

        if (Plugin.EnableSweeper?.Value != true)
        {
            return;
        }

        var sceneName = GetSceneName();
        if (_lastSceneName != sceneName)
        {
            _lastSceneName = sceneName;
            TextRuntime.ClearComponentCache();
            if (Plugin.SweepOnSceneChange?.Value == true)
            {
                TextRuntime.SweepActiveText();
            }
        }

        var now = Time.unscaledTime;
        if (Plugin.ContinuousSweeper?.Value != true)
        {
            return;
        }

        var interval = Math.Max(5.0f, Plugin.SweepIntervalSeconds?.Value ?? 15.0f);
        if (now < _nextSweep)
        {
            return;
        }

        _nextSweep = now + interval;
        TextRuntime.SweepActiveText();
    }

    private static string GetSceneName()
    {
        try
        {
            return SceneManager.GetActiveScene().name ?? string.Empty;
        }
        catch
        {
            return string.Empty;
        }
    }
}
