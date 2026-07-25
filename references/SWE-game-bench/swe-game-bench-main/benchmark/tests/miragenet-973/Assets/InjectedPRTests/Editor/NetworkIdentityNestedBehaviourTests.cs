#if UNITY_EDITOR
using System.Linq;
using NUnit.Framework;
using UnityEngine;
using Mirage;

public class TestNetworkBehaviour : NetworkBehaviour { }

public class NetworkIdentityNestedBehaviourTests
{
    [Test]
    public void NetworkBehaviours_DoesNotIncludeBehavioursFromNestedIdentity()
    {
        var parentGO = new GameObject("Parent");
        var identityA = parentGO.AddComponent<NetworkIdentity>();
        var parentBehaviour = parentGO.AddComponent<TestNetworkBehaviour>();

        var childGO = new GameObject("Child");
        childGO.transform.SetParent(parentGO.transform);
        var identityB = childGO.AddComponent<NetworkIdentity>();
        var childBehaviour = childGO.AddComponent<TestNetworkBehaviour>();

        var cacheField = typeof(NetworkIdentity).GetField(
            "networkBehavioursCache",
            System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
        if (cacheField != null) cacheField.SetValue(identityA, null);

        var staticCacheField = typeof(NetworkIdentity).GetField(
            "childNetworkBehavioursCache",
            System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic);
        if (staticCacheField != null)
        {
            var list = new System.Collections.Generic.List<NetworkBehaviour>();
            staticCacheField.SetValue(null, list);
        }

        var behaviours = identityA.NetworkBehaviours;

        Assert.IsFalse(
            behaviours.Contains(childBehaviour),
            "NetworkBehaviours on parent identity should not include behaviours " +
            "from nested child NetworkIdentity (base commit bug)."
        );

        Assert.IsTrue(
            behaviours.Contains(parentBehaviour),
            "NetworkBehaviours on parent identity should include its own behaviour."
        );

        Object.DestroyImmediate(parentGO);
    }
}
#endif