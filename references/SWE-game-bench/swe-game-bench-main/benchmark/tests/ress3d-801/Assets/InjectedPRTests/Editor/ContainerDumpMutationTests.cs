#if UNITY_EDITOR
using System;
using System.Collections;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

public class ContainerDumpMutationTests
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

    static Type FindExactType(string fullName)
    {
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            Type[] types;
            try { types = asm.GetTypes(); }
            catch (ReflectionTypeLoadException e) { types = e.Types; }
            catch { continue; }
            if (types == null) continue;
            foreach (var t in types)
                if (t != null && t.FullName == fullName)
                    return t;
        }
        return null;
    }

    static Type FindComponentType(string fullName)
    {
        var t = FindExactType(fullName);
        return t != null && typeof(Component).IsAssignableFrom(t) ? t : null;
    }

    static object MakeStoredItem(Type containerType, object item, Vector2Int position)
    {
        var storedItemType = containerType.GetNestedType("StoredItem", BF);
        Assert.IsNotNull(storedItemType, "Could not find Container.StoredItem");
        return Activator.CreateInstance(storedItemType, item, position);
    }

    [Test]
    public void Dump_ClearsAllItemsWithoutMutatingTheEnumeratedCollection()
    {
        var containerType = FindExactType("SS3D.Engine.Inventory.Container");
        var itemType = FindComponentType("SS3D.Engine.Inventory.Item");
        Assert.IsNotNull(containerType, "Could not find SS3D.Engine.Inventory.Container type");
        Assert.IsNotNull(itemType, "Could not find SS3D.Engine.Inventory.Item component type");

        var container = Activator.CreateInstance(containerType);

        var itemGO1 = new GameObject("HeldItem_1");
        var itemGO2 = new GameObject("HeldItem_2");
        var item1 = itemGO1.AddComponent(itemType);
        var item2 = itemGO2.AddComponent(itemType);

        var itemsField = containerType.GetField("items", BF);
        Assert.IsNotNull(itemsField, "Could not find Container.items");
        var storedItems = (IList)itemsField.GetValue(container);
        storedItems.Add(MakeStoredItem(containerType, item1, new Vector2Int(0, 0)));
        storedItems.Add(MakeStoredItem(containerType, item2, new Vector2Int(1, 0)));

        var setContainerUnchecked = itemType.GetMethod("SetContainerUnchecked", BF);
        Assert.IsNotNull(setContainerUnchecked, "Could not find Item.SetContainerUnchecked");
        setContainerUnchecked.Invoke(item1, new object[] { container });
        setContainerUnchecked.Invoke(item2, new object[] { container });

        var dumpMethod = containerType.GetMethod("Dump", BF);
        Assert.IsNotNull(dumpMethod, "Could not find Dump method");

        Assert.DoesNotThrow(() => dumpMethod.Invoke(container, null),
            "Base commit bug: Dump modified the same collection it was iterating over.");
        Assert.AreEqual(0, storedItems.Count, "Dump should clear all stored items.");

        var containerProperty = itemType.GetProperty("Container", BF);
        Assert.IsNotNull(containerProperty, "Could not find Item.Container property");
        Assert.IsNull(containerProperty.GetValue(item1), "First dumped item should no longer point at the container.");
        Assert.IsNull(containerProperty.GetValue(item2), "Second dumped item should no longer point at the container.");

        UnityEngine.Object.DestroyImmediate(itemGO1);
        UnityEngine.Object.DestroyImmediate(itemGO2);
    }
}
#endif