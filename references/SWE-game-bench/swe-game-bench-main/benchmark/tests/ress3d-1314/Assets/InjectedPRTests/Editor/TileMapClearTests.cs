#if UNITY_EDITOR
using System;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;

public class TileMapClearTests
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

    [Test]
    public void ClearTileObject_OnlyClearsRequestedDirection()
    {
        var tileMapType = FindType("TileMap");
        Assert.IsNotNull(tileMapType, "Could not find TileMap type");

        var tileMapGO = new GameObject("TileMap_Test");
        var tileMap = tileMapGO.AddComponent(tileMapType);

        var setup = tileMapType.GetMethod("Setup", BF);
        Assert.IsNotNull(setup, "Could not find Setup method");
        setup.Invoke(tileMap, new object[] { "testmap" });

        var clearMethod = tileMapType.GetMethod("ClearTileObject", BF);
        Assert.IsNotNull(clearMethod, "Could not find ClearTileObject method");

        var layerType = clearMethod.GetParameters()[1].ParameterType;
        var dirType = clearMethod.GetParameters()[2].ParameterType;

        object north = Enum.Parse(dirType, "North");
        object east = Enum.Parse(dirType, "East");

        var placedObjType = FindType("PlacedTileObject");
        var northGO = new GameObject("NorthObj");
        var northObj = northGO.AddComponent(placedObjType);
        var eastGO = new GameObject("EastObj");
        var eastObj = eastGO.AddComponent(placedObjType);

        var getTileLocation = tileMapType.GetMethod("GetTileLocation", BF);
        Assert.IsNotNull(getTileLocation, "Could not find GetTileLocation method");

        Vector3 pos = Vector3.zero;
        object targetLayer = Enum.GetValues(layerType).GetValue(0);

        var loc = getTileLocation.Invoke(tileMap, new object[] { targetLayer, pos });
        var addObjMethod = loc.GetType().GetMethod("AddPlacedObject", BF);
        addObjMethod.Invoke(loc, new object[] { northObj, north });
        addObjMethod.Invoke(loc, new object[] { eastObj, east });

        LogAssert.ignoreFailingMessages = true;

        bool threwExpectedNre = false;
        string stackTrace = "";

        try
        {
            clearMethod.Invoke(tileMap, new object[] { pos, targetLayer, north });
        }
        catch (TargetInvocationException ex)
        {
            threwExpectedNre = true;
            stackTrace = ex.InnerException.StackTrace ?? "";
        }

        LogAssert.ignoreFailingMessages = false;

        Assert.IsTrue(threwExpectedNre, "Pipeline Error: Expected an early headless NRE from DestroySelf(), but none was thrown.");

        bool calledDirectionalClear = stackTrace.Contains("TryClearPlacedObject");
        bool calledClearAll = stackTrace.Contains("ClearAllPlacedObject");

        Assert.IsTrue(calledDirectionalClear, "ClearTileObject did not clear the requested direction via TryClearPlacedObject().");
        Assert.IsFalse(calledClearAll, "Base commit bug: ClearTileObject called ClearAllPlacedObject() instead of TryClearPlacedObject()!");

        var tryGetMethod = loc.GetType().GetMethod("TryGetPlacedObject", BF);
        Assert.IsNotNull(tryGetMethod, "Could not find TryGetPlacedObject method");
        object[] tryGetArgs = { null, east };
        bool eastStillPresent = (bool)tryGetMethod.Invoke(loc, tryGetArgs);

        Assert.IsTrue(eastStillPresent, "Clearing North also removed the object placed East.");
        Assert.AreSame(eastObj, tryGetArgs[0], "The East object changed when only North should be cleared.");

        UnityEngine.Object.DestroyImmediate(tileMapGO);
        UnityEngine.Object.DestroyImmediate(northGO);
        UnityEngine.Object.DestroyImmediate(eastGO);
    }
}
#endif
