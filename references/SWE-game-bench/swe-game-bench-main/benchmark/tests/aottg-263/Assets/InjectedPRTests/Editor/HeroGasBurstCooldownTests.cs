#if UNITY_EDITOR
using System;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

public class HeroGasBurstCooldownTests
{
    static readonly BindingFlags BF =
        BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Static;

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
                if (t != null && (t.Name == name || (t.FullName != null && t.FullName.EndsWith("." + name))))
                    return t;
        }
        return null;
    }

    static FieldInfo FindFieldRecursive(Type type, string name)
    {
        while (type != null)
        {
            var f = type.GetField(name, BF);
            if (f != null) return f;
            type = type.BaseType;
        }
        return null;
    }

    static PropertyInfo FindPropertyRecursive(Type type, string name)
    {
        while (type != null)
        {
            var p = type.GetProperty(name, BF);
            if (p != null) return p;
            type = type.BaseType;
        }
        return null;
    }

    static void SetMember(object target, string name, object value)
    {
        var t = target.GetType();
        var field = FindFieldRecursive(t, name);
        if (field != null) { field.SetValue(target, value); return; }
        var prop = FindPropertyRecursive(t, name);
        if (prop != null && prop.CanWrite) { prop.SetValue(target, value, null); return; }
        // Auto-property backing field convention
        var backing = FindFieldRecursive(t, "<" + name + ">k__BackingField");
        if (backing != null) { backing.SetValue(target, value); return; }
        Assert.Fail("Could not find writable member '" + name + "' on " + t.FullName);
    }

    static float GetFloatMember(object target, string name)
    {
        var t = target.GetType();
        var field = FindFieldRecursive(t, name);
        if (field != null) return Convert.ToSingle(field.GetValue(target));
        var prop = FindPropertyRecursive(t, name);
        if (prop != null && prop.CanRead) return Convert.ToSingle(prop.GetValue(target, null));
        var backing = FindFieldRecursive(t, "<" + name + ">k__BackingField");
        if (backing != null) return Convert.ToSingle(backing.GetValue(target));
        throw new Exception("Could not read member '" + name + "' on " + t.FullName);
    }

    static void SafeInvoke(MethodInfo method, object target, object[] args)
    {
        try { method.Invoke(target, args); }
        catch (TargetInvocationException) { /* Dash has many downstream deps; we only care about gas mutation, which happens early. */ }
        catch { /* same */ }
    }

    [Test]
    public void Dash_DoesNotConsumeGasOnImmediateSecondCall()
    {
        var heroType = FindType("Hero");
        Assert.IsNotNull(heroType, "Pipeline error: Hero type not found.");

        var dash = heroType.GetMethod("Dash", BF);
        Assert.IsNotNull(dash, "Pipeline error: private Dash method not found.");

        var heroGO = new GameObject("Hero_CooldownBehaviorTest");
        try
        {
            var hero = heroGO.AddComponent(heroType);

            // Minimal preconditions so the gas-consumption branch is entered.
            SetMember(hero, "dashTime", 0f);
            SetMember(hero, "currentGas", 1000f);
            SetMember(hero, "totalGas", 1000f);
            SetMember(hero, "isMounted", false);

            float gasInitial = GetFloatMember(hero, "currentGas");

            SafeInvoke(dash, hero, new object[] { 0f, 1f });
            float gasAfterFirst = GetFloatMember(hero, "currentGas");

            Assert.Less(
                gasAfterFirst, gasInitial,
                "Pipeline sanity: first Dash invocation should consume some gas; if not, downstream setup is wrong and the rest of the test is meaningless.");

            // Rapid second call — cooldown should prevent additional gas consumption.
            SafeInvoke(dash, hero, new object[] { 0f, 1f });
            float gasAfterSecond = GetFloatMember(hero, "currentGas");

            Assert.AreEqual(
                gasAfterFirst, gasAfterSecond, 0.0001f,
                "Base commit bug: rapid second Dash also consumed gas — no cooldown gating the burst.");
        }
        finally
        {
            UnityEngine.Object.DestroyImmediate(heroGO);
        }
    }
}
#endif