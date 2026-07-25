#if UNITY_EDITOR
using System;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

public class PauseServiceRePauseTests
{
    static readonly BindingFlags BF =
        BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

    static Type FindType(string fullName)
    {
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            Type[] types;
            try { types = asm.GetTypes(); }
            catch (ReflectionTypeLoadException e) { types = e.Types; }
            catch { continue; }
            if (types == null) continue;
            foreach (var t in types)
                if (t != null && t.FullName == fullName) return t;
        }
        return null;
    }

    [Test]
    public void Pause_WhileUnpausing_RePausesCorrectly()
    {
        var serviceType = FindType("Assets.Scripts.Services.PauseService");
        Assert.IsNotNull(serviceType, "Pipeline error: PauseService type not found");

        var go = new GameObject("PauseService");
        var service = go.AddComponent(serviceType);
        Assert.IsNotNull(service, "Pipeline error: Could not AddComponent PauseService");

        var pauseMethod = serviceType.GetMethod("Pause", BF);
        Assert.IsNotNull(pauseMethod, "Pipeline error: Pause method not found");

        var pauseTimerProp = serviceType.GetProperty("PauseTimer", BF);
        var timerBackingField = serviceType.GetField("<PauseTimer>k__BackingField", BF);

        Func<float> getPauseTimer = () =>
        {
            if (pauseTimerProp != null) return (float)pauseTimerProp.GetValue(service);
            if (timerBackingField != null) return (float)timerBackingField.GetValue(service);
            return -1f;
        };

        pauseMethod.Invoke(service, new object[] { true, false });
        pauseMethod.Invoke(service, new object[] { false, true });
        Assert.AreEqual(0f, getPauseTimer(), "Setup error: PauseTimer should be 0f after unpausing");

        pauseMethod.Invoke(service, new object[] { true, false });

        float timerAfterRePause = getPauseTimer();
        Assert.AreEqual(
            float.MaxValue,
            timerAfterRePause,
            "Base commit bug: calling Pause(true) while unpausing did not fully re-pause the game."
        );

        UnityEngine.Object.DestroyImmediate(go);
    }
}
#endif