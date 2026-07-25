#if UNITY_EDITOR
using System;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

public class PauseServiceTests
{
    static readonly BindingFlags BF =
        BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

    static Type FindType(string name)
    {
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            Type[] types;
            try { types = asm.GetTypes(); }
            catch (ReflectionTypeLoadException e) { types = e.Types; }
            catch { continue; }
            if (types == null) continue;
            foreach (var t in types)
                if (t != null && t.Name == name) return t;
        }
        return null;
    }

    [Test]
    public void OnLevelWasLoaded_WhenPaused_CallsUnpause()
    {
        var serviceType = FindType("PauseService");
        Assert.IsNotNull(serviceType, "Pipeline error: PauseService type not found");

        var go = new GameObject("PauseService");
        var service = go.AddComponent(serviceType);
        Assert.IsNotNull(service, "Pipeline error: Could not AddComponent PauseService");

        var isPausedField = serviceType.GetField("isPaused", BF);
        Assert.IsNotNull(isPausedField, "Pipeline error: isPaused field not found");
        isPausedField.SetValue(service, true);

        var onUnPausedEvent = serviceType.GetEvent("OnUnPaused", BF);
        Assert.IsNotNull(onUnPausedEvent, "Pipeline error: OnUnPaused event not found");
        bool unpauseEventRaised = false;
        EventHandler handler = (sender, args) => unpauseEventRaised = true;
        onUnPausedEvent.AddEventHandler(service, handler);

        var pauseTimerProp = serviceType.GetProperty("PauseTimer", BF);
        if (pauseTimerProp != null && pauseTimerProp.CanWrite)
            pauseTimerProp.SetValue(service, float.MaxValue);
        else
        {
            var timerField = serviceType.GetField("PauseTimer", BF)
                          ?? serviceType.GetField("<PauseTimer>k__BackingField", BF);
            if (timerField != null) timerField.SetValue(service, float.MaxValue);
        }

        var onLevelLoaded = serviceType.GetMethod("OnLevelWasLoaded", BF);
        if (onLevelLoaded != null)
            onLevelLoaded.Invoke(service, null);

        float pauseTimer = float.MaxValue;
        if (pauseTimerProp != null)
            pauseTimer = (float)pauseTimerProp.GetValue(service);
        else
        {
            var timerField = serviceType.GetField("PauseTimer", BF)
                          ?? serviceType.GetField("<PauseTimer>k__BackingField", BF);
            if (timerField != null) pauseTimer = (float)timerField.GetValue(service);
        }

        Assert.AreEqual(
            0f,
            pauseTimer,
            "Base commit bug: PauseTimer was not reset on level load while paused."
        );
        Assert.IsTrue(
            unpauseEventRaised,
            "Level load did not raise OnUnPaused, so pause-message subscribers cannot clear the UI."
        );

        onUnPausedEvent.RemoveEventHandler(service, handler);
        UnityEngine.Object.DestroyImmediate(go);
    }
}
#endif
