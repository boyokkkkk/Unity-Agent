#if UNITY_EDITOR
using System;
using System.Reflection;
using System.Threading;
using NUnit.Framework;
using UnityEngine;

public class ServerStarterDisposesGameUpdaterTests
{
    static readonly BindingFlags InstanceFlags =
        BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;
    static readonly BindingFlags StaticFlags =
        BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public;

    static Type FindType(string fullName)
    {
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            Type[] types;
            try { types = asm.GetTypes(); }
            catch (ReflectionTypeLoadException e) { types = e.Types; }
            catch { continue; }

            if (types == null) continue;
            foreach (var type in types)
                if (type != null && type.FullName == fullName)
                    return type;
        }
        return null;
    }

    static Thread SleepingThread()
    {
        var thread = new Thread(() => Thread.Sleep(Timeout.Infinite));
        thread.IsBackground = true;
        thread.Start();
        return thread;
    }

    [Test]
    public void OnDestroy_DisposesGameUpdaterSubject()
    {
        var starterType = FindType("ServerStarter");
        var updaterType = FindType("Core.Update.GameUpdater");
        Assert.IsNotNull(starterType, "Pipeline error: ServerStarter type was not found.");
        Assert.IsNotNull(updaterType, "Pipeline error: Core.Update.GameUpdater type was not found.");

        var go = new GameObject("ServerStarterProbe");
        var starter = go.AddComponent(starterType);
        var serverThread = SleepingThread();
        var gameThread = SleepingThread();
        var autoSaveToken = new CancellationTokenSource();

        try
        {
            starterType.GetField("_serverUpdateThread", InstanceFlags).SetValue(starter, serverThread);
            starterType.GetField("_gameUpdateThread", InstanceFlags).SetValue(starter, gameThread);
            starterType.GetField("_autoSaveToken", InstanceFlags).SetValue(starter, autoSaveToken);

            var onDestroy = starterType.GetMethod("OnDestroy", InstanceFlags);
            Assert.IsNotNull(onDestroy, "Pipeline error: ServerStarter.OnDestroy was not found.");
            onDestroy.Invoke(starter, null);

            Assert.IsTrue(autoSaveToken.IsCancellationRequested,
                "Sanity check: OnDestroy should still cancel the auto-save token.");

            var update = updaterType.GetMethod("Update", StaticFlags);
            Assert.IsNotNull(update, "Pipeline error: GameUpdater.Update was not found.");

            var ex = Assert.Throws<TargetInvocationException>(() => update.Invoke(null, null));
            Assert.IsInstanceOf<ObjectDisposedException>(ex.InnerException,
                "GameUpdater.Update should throw after ServerStarter.OnDestroy disposes GameUpdater.");
        }
        finally
        {
            if (serverThread.IsAlive) serverThread.Abort();
            if (gameThread.IsAlive) gameThread.Abort();
            autoSaveToken.Dispose();
            UnityEngine.Object.DestroyImmediate(go);
        }
    }
}
#endif