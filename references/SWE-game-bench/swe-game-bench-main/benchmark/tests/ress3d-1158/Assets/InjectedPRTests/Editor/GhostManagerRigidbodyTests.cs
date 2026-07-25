#if UNITY_EDITOR
using System;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

public class GhostManagerRigidbodyTests
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
    public void CreateGhost_DisablesRigidbodyPhysicsOnPreviewObject()
    {
        var ghostManagerType = FindType("GhostManager");
        Assert.IsNotNull(ghostManagerType, "Could not find GhostManager type");

        var managerGO = new GameObject("GhostManager_Test");
        var manager = managerGO.AddComponent(ghostManagerType);

        var prefab = new GameObject("GhostPrefab_With_Rigidbody");
        var prefabRb = prefab.AddComponent<Rigidbody>();
        prefabRb.useGravity = true;
        prefabRb.isKinematic = false;
        prefab.AddComponent<BoxCollider>();

        var createGhost = ghostManagerType.GetMethod("CreateGhost", BF);
        Assert.IsNotNull(createGhost, "Could not find CreateGhost method");
        createGhost.Invoke(manager, new object[] { prefab });

        var ghostField = ghostManagerType.GetField("_ghostObject", BF);
        Assert.IsNotNull(ghostField, "Could not find _ghostObject field");
        var ghostObject = ghostField.GetValue(manager) as GameObject;
        Assert.IsNotNull(ghostObject, "CreateGhost did not create a ghost object");

        var ghostRb = ghostObject.GetComponent<Rigidbody>();
        Assert.IsNotNull(ghostRb, "Ghost object did not keep the prefab Rigidbody");
        Assert.IsFalse(ghostRb.useGravity, "Base commit bug: ghost Rigidbody still uses gravity and can fall away.");
        Assert.IsTrue(ghostRb.isKinematic, "Base commit bug: ghost Rigidbody is not kinematic and can push players.");

        UnityEngine.Object.DestroyImmediate(ghostObject);
        UnityEngine.Object.DestroyImmediate(prefab);
        UnityEngine.Object.DestroyImmediate(managerGO);
    }
}
#endif