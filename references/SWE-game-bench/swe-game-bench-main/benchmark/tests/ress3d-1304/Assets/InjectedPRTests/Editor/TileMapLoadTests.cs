#if UNITY_EDITOR
using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

public class TileMapLoadTests
{
    static BindingFlags BF = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Static;

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

    static void ForceEmptyEnumerables(object obj)
    {
        if (obj == null) return;
        var t = obj.GetType();
        foreach (var f in t.GetFields(BF))
        {
            if (f.FieldType == typeof(string)) continue;
            if (!typeof(IEnumerable).IsAssignableFrom(f.FieldType)) continue;

            SetEmptyEnumerableField(obj, f);
        }
    }

    static object CreateEmptyEnumerable(Type enumerableType)
    {
        if (enumerableType.IsArray)
        {
            var elem = enumerableType.GetElementType();
            return Array.CreateInstance(elem, 0);
        }

        if (enumerableType.IsGenericType && enumerableType.GetGenericTypeDefinition() == typeof(List<>))
        {
            var elem = enumerableType.GetGenericArguments()[0];
            var listType = typeof(List<>).MakeGenericType(elem);
            return Activator.CreateInstance(listType);
        }

        return null;
    }

    static void SetEmptyEnumerableField(object obj, FieldInfo field)
    {
        if (field == null) return;
        if (field.FieldType == typeof(string)) return;
        if (!typeof(IEnumerable).IsAssignableFrom(field.FieldType)) return;

        var emptyEnumerable = CreateEmptyEnumerable(field.FieldType);
        if (emptyEnumerable != null)
        {
            field.SetValue(obj, emptyEnumerable);
        }
    }

    static void TryRegisterSubsystem(object subsystemInstance)
    {
        if (subsystemInstance == null) return;

        var subsystemsType = FindType("Subsystems");
        if (subsystemsType == null) return;

        foreach (var m in subsystemsType.GetMethods(BF))
        {
            if (!m.IsStatic) continue;
            var ps = m.GetParameters();
            if (ps.Length == 1 && ps[0].ParameterType.IsAssignableFrom(subsystemInstance.GetType()))
            {
                try { m.Invoke(null, new object[] { subsystemInstance }); return; } catch { }
            }
            if (ps.Length == 1 && ps[0].ParameterType == typeof(object))
            {
                try { m.Invoke(null, new object[] { subsystemInstance }); return; } catch { }
            }
        }

        foreach (var f in subsystemsType.GetFields(BF))
        {
            if (!f.IsStatic) continue;
            if (!typeof(IDictionary).IsAssignableFrom(f.FieldType)) continue;

            try
            {
                var dict = f.GetValue(null) as IDictionary;
                if (dict == null) continue;
                dict[subsystemInstance.GetType()] = subsystemInstance;
                return;
            }
            catch { }
        }
    }

    [Test]
    public void Load_EmptyMap_FiresOnMapLoadedEvent()
    {
        var tileMapType = FindType("TileMap");
        Assert.IsNotNull(tileMapType, "Could not find TileMap type");

        var savedMapType = FindType("SavedTileMap");
        Assert.IsNotNull(savedMapType, "Could not find SavedTileMap type");

        var tileMapGO = new GameObject("TileMap_Test");
        var tileMap = tileMapGO.AddComponent(tileMapType);

        var setupMethod = tileMapType.GetMethod("Setup", BF);
        Assert.IsNotNull(setupMethod, "Could not find TileMap.Setup method");
        setupMethod.Invoke(tileMap, new object[] { "TileMap_Test" });

        var tileSystemType = FindType("TileSystem");
        Assert.IsNotNull(tileSystemType, "Could not find TileSystem type");
        var tileSystemGO = new GameObject("TileSystem_Test");
        var tileSystem = tileSystemGO.AddComponent(tileSystemType);

        ForceEmptyEnumerables(tileSystem);
        ForceEmptyEnumerables(tileMap);
        TryRegisterSubsystem(tileSystem);

        var onMapLoadedEvent = tileMapType.GetEvent("OnMapLoaded", BF);
        Assert.IsNotNull(onMapLoadedEvent, "Could not find OnMapLoaded event");

        bool eventFired = false;
        EventHandler handler = (s, e) => eventFired = true;
        onMapLoadedEvent.AddEventHandler(tileMap, handler);

        var savedMap = Activator.CreateInstance(savedMapType);
        ForceEmptyEnumerables(savedMap);

        var savedItemListField = savedMapType.GetField("savedItemList", BF);
        if (savedItemListField != null)
        {
            SetEmptyEnumerableField(savedMap, savedItemListField);
        }

        var savedTileLists = new[]
        {
            "savedFloorTiles",
            "savedWallmountLatticeObjects",
            "savedWallmountFulltileObjects",
            "savedWindowObjects",
            "savedGrilleObjects",
            "savedFloorPlenumObjects"
        };
        foreach (var fieldName in savedTileLists)
        {
            var f = savedMapType.GetField(fieldName, BF);
            if (f != null)
            {
                SetEmptyEnumerableField(savedMap, f);
            }
        }

        var loadMethod = tileMapType.GetMethod("Load", BF);
        Assert.IsNotNull(loadMethod, "Could not find Load method");

        loadMethod.Invoke(tileMap, new object[] { savedMap });

        Assert.IsTrue(eventFired, "Base commit bug: OnMapLoaded event was not fired when loading a map containing saved item data.");

        UnityEngine.Object.DestroyImmediate(tileSystemGO);
        UnityEngine.Object.DestroyImmediate(tileMapGO);
    }
}
#endif
