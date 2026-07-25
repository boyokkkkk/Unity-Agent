#if UNITY_EDITOR
using System.Reflection;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;

public class ConstructionHologramSMRTests
{
    static BindingFlags BF = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

    static System.Type FindType(string name)
    {
        foreach (var asm in System.AppDomain.CurrentDomain.GetAssemblies())
        {
            System.Type[] types;
            try { types = asm.GetTypes(); }
            catch (System.Reflection.ReflectionTypeLoadException e) { types = e.Types; }
            catch { continue; }
            if (types == null) continue;
            foreach (var t in types)
                if (t != null && t.Name == name) return t;
        }
        return null;
    }

    [Test]
    public void ChangeHologramColor_AppliesGhostMat_ToSkinnedMeshRenderers()
    {
        var hologramType = FindType("ConstructionHologram");
        Assert.IsNotNull(hologramType, "Could not find ConstructionHologram type");

        var hologramGO = new GameObject("Hologram");
        var childGO = new GameObject("SkinnedChild");
        childGO.transform.SetParent(hologramGO.transform);

        var smr = childGO.AddComponent<SkinnedMeshRenderer>();
        var originalMat = new Material(Shader.Find("Standard") ?? Shader.Find("Hidden/InternalErrorShader"));
        smr.sharedMaterials = new Material[] { originalMat };

        var hologram = System.Runtime.Serialization.FormatterServices.GetUninitializedObject(hologramType);

        var hologramField = hologramType.GetField("_hologram", BF)
            ?? hologramType.GetField("hologram", BF);
        hologramField.SetValue(hologram, hologramGO);

        var modeType = FindType("ConstructionMode");
        Assert.IsNotNull(modeType, "Could not find ConstructionMode enum");
        object dummyMode = System.Enum.ToObject(modeType, 999);

        var method = hologramType.GetMethod("ChangeHologramColor", BF);

        LogAssert.ignoreFailingMessages = true;

        method.Invoke(hologram, new object[] { dummyMode });

        LogAssert.ignoreFailingMessages = false;

        Assert.AreNotEqual(originalMat, smr.sharedMaterials[0],
            "Base commit bug: SkinnedMeshRenderer materials were not updated by ChangeHologramColor.");

        Object.DestroyImmediate(childGO);
        Object.DestroyImmediate(hologramGO);
    }
}
#endif