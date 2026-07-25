#if UNITY_EDITOR
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;
using Mirror;

public class ProbeNetworkBehaviour : NetworkBehaviour
{
}

public class DisabledNetworkBehaviourIdentityTests
{
    [Test]
    public void NetIdentity_ReturnsIdentityOnDisabledSameGameObject()
    {
        var go = new GameObject("DisabledSceneObject");

        try
        {
            var identity = go.AddComponent<NetworkIdentity>();
            var behaviour = go.AddComponent<ProbeNetworkBehaviour>();
            go.SetActive(false);

            LogAssert.NoUnexpectedReceived();

            Assert.AreSame(
                identity,
                behaviour.NetIdentity,
                "NetworkBehaviour.NetIdentity should resolve NetworkIdentity on the same disabled GameObject.");

            LogAssert.NoUnexpectedReceived();
        }
        finally
        {
            UnityEngine.Object.DestroyImmediate(go);
        }
    }
}
#endif