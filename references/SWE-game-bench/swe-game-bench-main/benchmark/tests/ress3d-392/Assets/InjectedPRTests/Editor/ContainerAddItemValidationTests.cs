#if UNITY_EDITOR
using System;
using System.Collections;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

public class ContainerAddItemValidationTests
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

    static object SeedOneSlot(object container, Type containerType)
    {
        var slotType = containerType.GetNestedType("SlotType", BF);
        Assert.IsNotNull(slotType, "Could not find Container.SlotType");

        var slotsField = containerType.GetField("slots", BF);
        Assert.IsNotNull(slotsField, "Could not find Container.slots");
        var slots = Array.CreateInstance(slotType, 1);
        slots.SetValue(Enum.Parse(slotType, "General"), 0);
        slotsField.SetValue(container, slots);

        var itemsField = containerType.GetField("items", BF);
        Assert.IsNotNull(itemsField, "Could not find Container.items");
        var items = itemsField.GetValue(container);
        items.GetType().GetMethod("Clear", BF, null, Type.EmptyTypes, null).Invoke(items, null);
        items.GetType().GetMethod("Add", BF, null, new[] { typeof(GameObject) }, null).Invoke(items, new object[] { null });
        return items;
    }

    static object GetStoredItem(object items, int index)
    {
        return items.GetType().GetProperty("Item", BF).GetValue(items, new object[] { index });
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
    public void AddItem_RejectsGameObjectsMissingRequiredItemPhysicsComponents()
    {
        var containerType = FindExactType("SS3D.Engine.Inventory.Container");
        Assert.IsNotNull(containerType, "Could not find SS3D.Engine.Inventory.Container");

        var containerGO = new GameObject("Container_Test");
        var container = containerGO.AddComponent(containerType);
        var items = SeedOneSlot(container, containerType);

        var invalidItem = new GameObject("InvalidItem_MissingComponents");
        var addItem = containerType.GetMethod("AddItem", BF, null, new[] { typeof(int), typeof(GameObject) }, null);
        Assert.IsNotNull(addItem, "Could not find AddItem(int, GameObject)");

        bool oldServerActive = SetNetworkServerActive(true);
        try
        {
            addItem.Invoke(container, new object[] { 0, invalidItem });
            Assert.IsNull(GetStoredItem(items, 0), "Base commit bug: invalid GameObjects without Item/Rigidbody/Collider were stored in the container.");
        }
        finally
        {
            SetNetworkServerActive(oldServerActive);
            UnityEngine.Object.DestroyImmediate(invalidItem);
            UnityEngine.Object.DestroyImmediate(containerGO);
        }
    }
}
#endif