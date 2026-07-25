#if UNITY_EDITOR
using System;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

public class ContainerAddItemActivationTests
{
    static BindingFlags BF = BindingFlags.Instance | BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public;

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
        var type = FindExactType(fullName);
        return type != null && typeof(Component).IsAssignableFrom(type) ? type : null;
    }

    static void SeedOneSlot(object container, Type containerType)
    {
        var slotsField = containerType.GetField("slots", BF);
        Assert.IsNotNull(slotsField, "Could not find Container.slots");
        slotsField.SetValue(container, 1);

        var itemsField = containerType.GetField("items", BF);
        Assert.IsNotNull(itemsField, "Could not find Container.items");
        var items = itemsField.GetValue(container);
        items.GetType().GetMethod("Clear", BF, null, Type.EmptyTypes, null).Invoke(items, null);
        items.GetType().GetMethod("Add", BF, null, new[] { typeof(GameObject) }, null).Invoke(items, new object[] { null });

        var volumeLimited = containerType.GetField("volumeLimited", BF);
        if (volumeLimited != null)
            volumeLimited.SetValue(container, false);
    }

    static bool SetNetworkServerActive(bool active)
    {
        var networkServerType = FindExactType("Mirror.NetworkServer");
        Assert.IsNotNull(networkServerType, "Could not find Mirror.NetworkServer");

        var activeProperty = networkServerType.GetProperty("active", BF);
        if (activeProperty != null)
        {
            bool previous = (bool)activeProperty.GetValue(null, null);
            var setter = activeProperty.GetSetMethod(true);
            Assert.IsNotNull(setter, "Could not set Mirror.NetworkServer.active");
            setter.Invoke(null, new object[] { active });
            return previous;
        }

        var activeField = networkServerType.GetField("active", BF);
        Assert.IsNotNull(activeField, "Could not find Mirror.NetworkServer.active");
        bool oldValue = (bool)activeField.GetValue(null);
        activeField.SetValue(null, active);
        return oldValue;
    }

    [Test]
    public void AddItemToSpecificSlot_DeactivatesStoredItem()
    {
        var containerType = FindExactType("SS3D.Engine.Inventory.Container");
        var itemType = FindComponentType("SS3D.Engine.Inventory.Item");
        Assert.IsNotNull(containerType, "Could not find SS3D.Engine.Inventory.Container");
        Assert.IsNotNull(itemType, "Could not find SS3D.Engine.Inventory.Item");

        var containerGO = new GameObject("Container_Test");
        var container = containerGO.AddComponent(containerType);
        SeedOneSlot(container, containerType);

        var itemGO = new GameObject("StoredItem");
        itemGO.AddComponent(itemType);
        itemGO.AddComponent<Rigidbody>();
        itemGO.AddComponent<BoxCollider>();
        itemGO.SetActive(true);

        var addItem = containerType.GetMethod("AddItem", BF, null, new[] { typeof(int), typeof(GameObject) }, null);
        Assert.IsNotNull(addItem, "Could not find AddItem(int, GameObject)");

        bool oldServerActive = SetNetworkServerActive(true);
        try
        {
            addItem.Invoke(container, new object[] { 0, itemGO });
            Assert.IsFalse(itemGO.activeSelf, "Base commit bug: items stored through AddItem(slot, item) remained active in the world.");
        }
        finally
        {
            SetNetworkServerActive(oldServerActive);
            UnityEngine.Object.DestroyImmediate(itemGO);
            UnityEngine.Object.DestroyImmediate(containerGO);
        }
    }
}
#endif