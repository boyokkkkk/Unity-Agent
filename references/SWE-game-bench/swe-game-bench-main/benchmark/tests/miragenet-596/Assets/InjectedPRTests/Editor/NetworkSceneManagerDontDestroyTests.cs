#if UNITY_EDITOR
using System;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

public class NetworkSceneManagerDontDestroyTests
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
    public void Start_WhenDontDestroyFalse_DoesNotMoveToGlobalScene()
    {
        var managerType = FindType("Mirage.NetworkSceneManager");
        Assert.IsNotNull(managerType, "Pipeline error: NetworkSceneManager type not found");

        var go = new GameObject("NetworkSceneManager");
        var manager = go.AddComponent(managerType);
        Assert.IsNotNull(manager, "Pipeline error: Could not AddComponent NetworkSceneManager");

        var dontDestroyField = managerType.GetField("DontDestroy", BF);
        if (dontDestroyField != null)
            dontDestroyField.SetValue(manager, false);

        var startMethod = managerType.GetMethod("Start", BF);
        Assert.IsNotNull(startMethod, "Pipeline error: Start method not found");

        startMethod.Invoke(manager, null);

        string sceneName = go.scene.name;

        Assert.AreNotEqual("DontDestroyOnLoad", sceneName,
            "Base commit bug: Start() always called DontDestroyOnLoad regardless of DontDestroy flag. " +
            "Scene was: " + sceneName);

        UnityEngine.Object.DestroyImmediate(go);
    }
}
#endif