#if UNITY_EDITOR
using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

public class InventoryContainerDeduplicationTests
{
    static BindingFlags BF = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

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
    public void GetContainers_DoesNotReturnHeldMobileContainerTwice()
    {
        var inventoryType = FindType("Inventory");
        var containerType = FindComponentType("SS3D.Engine.Inventory.Container");
        Assert.IsNotNull(inventoryType, "Could not find Inventory type");
        Assert.IsNotNull(containerType, "Could not find SS3D.Engine.Inventory.Container component type");

        var playerGO = new GameObject("PlayerInventorySource");
        var inventory = playerGO.AddComponent(inventoryType);
        var rootContainer = playerGO.AddComponent(containerType);

        var heldGO = new GameObject("HeldToolboxSource");
        heldGO.transform.SetParent(playerGO.transform);
        var heldContainer = heldGO.AddComponent(containerType);

        var sourcesField = inventoryType.GetField("objectSources", BF);
        Assert.IsNotNull(sourcesField, "Could not find Inventory.objectSources");
        var sources = sourcesField.GetValue(inventory);

        var addMethod = sources.GetType().GetMethod("Add", new[] { typeof(GameObject) });
        Assert.IsNotNull(addMethod, "Could not add objects to Inventory.objectSources");
        addMethod.Invoke(sources, new object[] { playerGO });
        addMethod.Invoke(sources, new object[] { heldGO });

        var getContainers = inventoryType.GetMethod("GetContainers", BF);
        Assert.IsNotNull(getContainers, "Could not find GetContainers method");
        var containers = ((IEnumerable)getContainers.Invoke(inventory, null)).Cast<object>().ToList();

        Assert.AreEqual(containers.Distinct().Count(), containers.Count,
            "Base commit bug: GetContainers returned the same mobile container more than once.");
        Assert.AreEqual(1, containers.Count(c => ReferenceEquals(c, heldContainer)),
            "The held/mobile container should appear exactly once.");
        Assert.Contains(rootContainer, containers);

        UnityEngine.Object.DestroyImmediate(heldGO);
        UnityEngine.Object.DestroyImmediate(playerGO);
    }
}
#endif