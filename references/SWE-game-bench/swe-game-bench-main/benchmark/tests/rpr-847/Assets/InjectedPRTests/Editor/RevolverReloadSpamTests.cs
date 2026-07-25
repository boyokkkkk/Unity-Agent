#if UNITY_EDITOR
using System.Reflection;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;

public class RevolverReloadSpamTests
{
    static readonly BindingFlags Flags = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

    static void SetField(object target, string name, object value)
    {
        var type = target.GetType();
        while (type != null)
        {
            var field = type.GetField(name, Flags);
            if (field != null)
            {
                field.SetValue(target, value);
                return;
            }
            type = type.BaseType;
        }
        Assert.Fail("Pipeline error: missing field " + name);
    }

    [Test]
    public void Reload_WhenAlreadyReloading_DoesNotStartSecondReload()
    {
        LogAssert.ignoreFailingMessages = true;

        var gunObject = new GameObject("gun");
        var revolverObject = new GameObject("revolver");
        var animatorObject = new GameObject("animator");

        try
        {
            var stats = ScriptableObject.CreateInstance<GunStats>();
            stats.Ammo = 0;

            var gun = gunObject.AddComponent<GunController>();
            gun.stats = stats;

            revolverObject.transform.SetParent(gunObject.transform, false);
            var revolver = revolverObject.AddComponent<Revolver>();

            var animator = animatorObject.AddComponent<Animator>();
            SetField(revolver, "animator", animator);

            int reloadEvents = 0;
            gun.onReload += _ => reloadEvents++;

            revolver.Start();

            var reload = typeof(Revolver).GetMethod("Reload", Flags);
            Assert.IsNotNull(reload, "Pipeline error: Revolver.Reload should exist.");

            reload.Invoke(revolver, new object[] { stats });
            reload.Invoke(revolver, new object[] { stats });

            Assert.AreEqual(
                1,
                reloadEvents,
                "Spamming reload while the revolver reload animation is already in progress should not invoke another reload.");
        }
        finally
        {
            Object.DestroyImmediate(animatorObject);
            Object.DestroyImmediate(revolverObject);
            Object.DestroyImmediate(gunObject);
            LogAssert.ignoreFailingMessages = false;
        }
    }
}
#endif