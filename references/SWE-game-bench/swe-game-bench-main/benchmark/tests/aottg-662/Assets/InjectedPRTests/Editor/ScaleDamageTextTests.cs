#if UNITY_EDITOR
using System;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

public class ScaleDamageTextTests
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
    public void ScaleDamageText_UsesFloorNotRound()
    {
        var hudType = FindType("Assets.Scripts.UI.InGame.HUD.HUD");
        Assert.IsNotNull(hudType, "Pipeline error: HUD type not found");

        var go = new GameObject("HUD");
        var hud = go.AddComponent(hudType);
        Assert.IsNotNull(hud, "Pipeline error: Could not AddComponent HUD");

        var method = hudType.GetMethod("ScaleDamageText", BF);
        Assert.IsNotNull(method, "Pipeline error: ScaleDamageText method not found");

        int result = (int)method.Invoke(hud, new object[] { 50 });
        Assert.AreEqual(
            158,
            result,
            "Base commit bug: ScaleDamageText used rounding instead of floor semantics for damage=50."
        );

        UnityEngine.Object.DestroyImmediate(go);
    }
}
#endif