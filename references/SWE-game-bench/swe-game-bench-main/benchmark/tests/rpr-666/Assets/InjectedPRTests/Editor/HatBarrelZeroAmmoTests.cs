#if UNITY_EDITOR
using System.Collections.Generic;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;

public class HatBarrelZeroAmmoTests
{
    static readonly BindingFlags Flags = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

    static void SetField(object target, string name, object value)
    {
        var field = target.GetType().GetField(name, Flags);
        Assert.IsNotNull(field, "Pipeline error: missing field " + name);
        field.SetValue(target, value);
    }

    [Test]
    public void OnFire_WithZeroAmmo_DoesNotIndexNegativeAmmunitionSlot()
    {
        LogAssert.ignoreFailingMessages = true;

        var root = new GameObject("hat-barrel-model");
        var animatorObject = new GameObject("animator");
        var bullet = new GameObject("bullet");
        var ammoObjects = new List<GameObject>();

        try
        {
            var model = root.AddComponent<HatBarrelModel>();
            var animator = animatorObject.AddComponent<Animator>();
            animatorObject.transform.SetParent(root.transform);

            for (int i = 0; i < 5; i++)
            {
                var ammo = new GameObject("ammo-" + i);
                ammo.SetActive(true);
                ammoObjects.Add(ammo);
            }

            SetField(model, "animator", animator);
            SetField(model, "bullet", bullet);
            SetField(model, "ammunition", ammoObjects);
            SetField(model, "magazineSize", ammoObjects.Count);

            var stats = ScriptableObject.CreateInstance<GunStats>();
            stats.Ammo = 0;

            Assert.DoesNotThrow(
                () => model.OnFire(stats),
                "OnFire should clamp the ammo start index. The old code started at stats.Ammo - 2 and indexed ammunition[-2].");

            foreach (var ammo in ammoObjects)
            {
                Assert.IsFalse(ammo.activeSelf, "Zero ammo should hide all visible ammunition objects.");
            }
        }
        finally
        {
            Object.DestroyImmediate(root);
            Object.DestroyImmediate(animatorObject);
            Object.DestroyImmediate(bullet);
            foreach (var ammo in ammoObjects)
            {
                Object.DestroyImmediate(ammo);
            }
            LogAssert.ignoreFailingMessages = false;
        }
    }
}
#endif