#if UNITY_EDITOR
using System;
using System.Collections;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

public class AttachedContainerStartFilterTests
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

    static object CreateFilterInstance(Type filterType)
    {
        Type concrete = null;
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            Type[] types;
            try { types = asm.GetTypes(); }
            catch (ReflectionTypeLoadException e) { types = e.Types; }
            catch { continue; }
            if (types == null) continue;
            foreach (var t in types)
                if (t != null && filterType.IsAssignableFrom(t) && !t.IsAbstract)
                {
                    concrete = t;
                    break;
                }
            if (concrete != null) break;
        }
        Assert.IsNotNull(concrete, "Could not find a concrete Filter type");

        if (typeof(ScriptableObject).IsAssignableFrom(concrete))
            return ScriptableObject.CreateInstance(concrete);

        return Activator.CreateInstance(concrete);
    }

    [Test]
    public void Start_AppliesConfiguredStartFilterToCreatedContainer()
    {
        var generatorType = FindComponentType("SS3D.Engine.Inventory.AttachedContainerGenerator");
        var attachedContainerType = FindComponentType("SS3D.Engine.Inventory.AttachedContainer");
        Assert.IsNotNull(generatorType, "Could not find AttachedContainerGenerator");
        Assert.IsNotNull(attachedContainerType, "Could not find AttachedContainer");

        var startFilterField = generatorType.GetField("StartFilter", BF);
        Assert.IsNotNull(startFilterField, "Base commit bug: generator has no StartFilter field to apply.");

        var go = new GameObject("AttachedContainerGenerator_Test");
        var attached = go.AddComponent(attachedContainerType);
        var generator = go.AddComponent(generatorType);
        var filter = CreateFilterInstance(startFilterField.FieldType);

        generatorType.GetField("AttachedContainer", BF).SetValue(generator, attached);
        generatorType.GetField("Size", BF).SetValue(generator, new Vector2Int(1, 1));
        startFilterField.SetValue(generator, filter);

        var start = generatorType.GetMethod("Start", BF);
        Assert.IsNotNull(start, "Could not find Start method");
        start.Invoke(generator, null);

        var container = attachedContainerType.GetProperty("Container", BF).GetValue(attached);
        Assert.IsNotNull(container, "Start did not create a container");
        var filtersField = container.GetType().GetField("Filters", BF);
        Assert.IsNotNull(filtersField, "Created container has no Filters list");
        var filters = (IList)filtersField.GetValue(container);

        Assert.Contains(filter, filters, "Base commit bug: StartFilter was not copied into the generated container filters.");

        if (filter is ScriptableObject so)
            UnityEngine.Object.DestroyImmediate(so);
        UnityEngine.Object.DestroyImmediate(go);
    }
}
#endif