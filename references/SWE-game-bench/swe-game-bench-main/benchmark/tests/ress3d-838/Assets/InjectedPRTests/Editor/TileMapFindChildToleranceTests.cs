#if UNITY_EDITOR
using System;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

public class TileMapFindChildToleranceTests
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
    public void FindChild_MatchesSmallFloatingPointOffsetsOnXZPlane()
    {
        var tileMapType = FindType("TileMap");
        Assert.IsNotNull(tileMapType, "Could not find TileMap type");

        var go = new GameObject("TileMap_Test");
        var tileMap = go.AddComponent(tileMapType);

        var setup = tileMapType.GetMethod("Setup", BF);
        Assert.IsNotNull(setup, "Could not find Setup method");
        setup.Invoke(tileMap, new object[] { "test" });

        var getLayer = tileMapType.GetMethod("GetOrCreateLayerObject", BF);
        var findChild = tileMapType.GetMethod("FindChild", BF);
        Assert.IsNotNull(getLayer, "Could not find GetOrCreateLayerObject");
        Assert.IsNotNull(findChild, "Could not find FindChild");

        var layerType = findChild.GetParameters()[0].ParameterType;
        object layer = Enum.GetValues(layerType).GetValue(0);
        var layerObject = (GameObject)getLayer.Invoke(tileMap, new object[] { layer });

        var expectedPosition = new Vector3(3f, 0f, 4f);
        var child = new GameObject("PlacedChild_0");
        child.transform.SetParent(layerObject.transform);
        child.transform.position = expectedPosition + new Vector3(0.02f, 0.4f, -0.02f);

        var result = findChild.Invoke(tileMap, new object[] { layer, 0, expectedPosition }) as GameObject;

        Assert.AreSame(child, result, "Base commit bug: FindChild required exact X/Z equality instead of tolerating tiny saved-position offsets.");

        UnityEngine.Object.DestroyImmediate(go);
    }
}
#endif