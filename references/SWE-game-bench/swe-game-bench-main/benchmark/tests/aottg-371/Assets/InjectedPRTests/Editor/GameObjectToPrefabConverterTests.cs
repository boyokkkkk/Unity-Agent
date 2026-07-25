#if UNITY_EDITOR
using System;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;
using UnityEditor;

public class GameObjectToPrefabConverterTests
{
    static readonly BindingFlags BF =
        BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

    static Type FindType(string fullName)
    {
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            Type[] types;
            try { types = asm.GetTypes(); }
            catch (ReflectionTypeLoadException e) { types = e.Types; }
            catch { continue; }
            if (types == null) continue;
            foreach (var t in types)
                if (t != null && t.FullName == fullName) return t;
        }
        return null;
    }

    [Test]
    public void Multiply_ScalesVectorCorrectly()
    {
        var converterType = FindType("Assets.Editor.GameObjectToPrefabConverter");
        Assert.IsNotNull(converterType, "Base commit: GameObjectToPrefabConverter does not exist yet.");

        var converter = ScriptableObject.CreateInstance(converterType);
        Assert.IsNotNull(converter, "Pipeline error: Could not instantiate GameObjectToPrefabConverter");

        var scaleMultField = converterType.GetField("ScaleMultiplier", BF);
        Assert.IsNotNull(scaleMultField, "Pipeline error: ScaleMultiplier field not found");
        scaleMultField.SetValue(converter, new Vector3(2f, 2f, 2f));

        var multiplyMethod = converterType.GetMethod("Multiply", BF);
        Assert.IsNotNull(multiplyMethod, "Pipeline error: Multiply method not found");

        var lossyScale = new Vector3(1f, 2f, 3f);
        var prefabScale = new Vector3(4f, 5f, 6f);
        var expected = new Vector3(8f, 20f, 36f);

        var result = (Vector3)multiplyMethod.Invoke(converter, new object[] { lossyScale, prefabScale });

        Assert.AreEqual(expected.x, result.x, 0.0001f, "X component mismatch");
        Assert.AreEqual(expected.y, result.y, 0.0001f, "Y component mismatch");
        Assert.AreEqual(expected.z, result.z, 0.0001f, "Z component mismatch");

        UnityEngine.Object.DestroyImmediate(converter);
    }
}
#endif