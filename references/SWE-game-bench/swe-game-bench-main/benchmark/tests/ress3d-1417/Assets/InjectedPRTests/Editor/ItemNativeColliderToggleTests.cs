#if UNITY_EDITOR
using System;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

public class ItemNativeColliderToggleTests
{
    static BindingFlags BF = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

    static Type FindComponentType(string fullName)
    {
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            Type[] types;
            try { types = asm.GetTypes(); }
            catch (ReflectionTypeLoadException e) { types = e.Types; }
            catch { continue; }
            if (types == null) continue;
            foreach (var t in types)
                if (t != null && t.FullName == fullName && typeof(Component).IsAssignableFrom(t))
                    return t;
        }
        return null;
    }

    [Test]
    public void FreezeAndUnfreeze_ToggleAllNativeChildColliders()
    {
        var itemType = FindComponentType("SS3D.Systems.Inventory.Items.Item");
        Assert.IsNotNull(itemType, "Could not find Item type");

        var itemGO = new GameObject("ColliderItem");
        itemGO.AddComponent(itemType);
        var rootCollider = itemGO.AddComponent<BoxCollider>();

        var childGO = new GameObject("NativeColliderChild");
        childGO.transform.SetParent(itemGO.transform);
        var childCollider = childGO.AddComponent<BoxCollider>();

        var freeze = itemType.GetMethod("Freeze", BF);
        var unfreeze = itemType.GetMethod("Unfreeze", BF);
        Assert.IsNotNull(freeze, "Could not find Freeze");
        Assert.IsNotNull(unfreeze, "Could not find Unfreeze");

        freeze.Invoke(itemGO.GetComponent(itemType), null);

        Assert.IsFalse(rootCollider.enabled, "Freeze should disable the root item collider.");
        Assert.IsFalse(childCollider.enabled, "Base commit bug: Freeze did not disable native child colliders.");

        unfreeze.Invoke(itemGO.GetComponent(itemType), null);

        Assert.IsTrue(rootCollider.enabled, "Unfreeze should restore the root item collider.");
        Assert.IsTrue(childCollider.enabled, "Unfreeze should restore native child colliders.");

        UnityEngine.Object.DestroyImmediate(itemGO);
    }
}
#endif