#if UNITY_EDITOR
using System;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;
using Mirror;

public class LegacyServerOnlyBehaviorTests
{
    static readonly BindingFlags BF =
        BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

    class CapturingConnection : NetworkConnection
    {
        public int spawnMessages;
        public SpawnMessage lastSpawnMessage;

        public CapturingConnection() : base(PipeConnection.CreatePipe().Item1)
        {
            IsReady = true;
        }

        public override void Send<T>(T msg, int channelId = Channel.Reliable)
        {
            if (msg is SpawnMessage)
            {
                spawnMessages++;
                lastSpawnMessage = (SpawnMessage)(object)msg;
            }
        }
    }

    static void SetProperty(object target, string name, object value)
    {
        var property = target.GetType().GetProperty(name, BF);
        Assert.IsNotNull(property, "Pipeline error: property not found: " + name);
        var setter = property.GetSetMethod(true);
        Assert.IsNotNull(setter, "Pipeline error: property has no setter: " + name);
        setter.Invoke(target, new object[] { value });
    }

    static void SetField(object target, string name, object value)
    {
        var field = target.GetType().GetField(name, BF);
        Assert.IsNotNull(field, "Pipeline error: field not found: " + name);
        field.SetValue(target, value);
    }

    static void SetLegacyServerOnlyIfPresent(NetworkIdentity identity)
    {
        var field = typeof(NetworkIdentity).GetField("serverOnly", BF);
        if (field != null)
        {
            field.SetValue(identity, true);
        }
    }

    static void InvokeSendSpawnMessage(ServerObjectManager manager, NetworkIdentity identity, INetworkConnection conn)
    {
        var method = typeof(ServerObjectManager).GetMethod("SendSpawnMessage", BF);
        Assert.IsNotNull(method, "Pipeline error: ServerObjectManager.SendSpawnMessage not found");
        method.Invoke(manager, new object[] { identity, conn });
    }

    [Test]
    public void LegacyServerOnlyState_DoesNotSuppressClientStateOrSpawnMessage()
    {
        var managerGO = new GameObject("ServerObjectManager");
        var manager = managerGO.AddComponent<ServerObjectManager>();

        var clientGO = new GameObject("NetworkClient");
        var client = clientGO.AddComponent<NetworkClient>();

        var identityGO = new GameObject("NetworkIdentity");
        var identity = identityGO.AddComponent<NetworkIdentity>();

        var connection = new CapturingConnection();

        try
        {
            SetProperty(identity, "NetId", (uint)42);
            SetProperty(identity, "Client", client);
            SetField(client, "connectState", ConnectState.Connected);
            SetLegacyServerOnlyIfPresent(identity);

            Assert.IsTrue(identity.IsClient,
                "A spawned identity with an active client should remain a client object even if legacy server-only state exists.");

            InvokeSendSpawnMessage(manager, identity, connection);

            Assert.AreEqual(1, connection.spawnMessages,
                "Ready clients should still receive one spawn message for the identity.");
            Assert.AreEqual(42u, connection.lastSpawnMessage.netId,
                "Spawn message should describe the identity being spawned.");
        }
        finally
        {
            UnityEngine.Object.DestroyImmediate(identityGO);
            UnityEngine.Object.DestroyImmediate(clientGO);
            UnityEngine.Object.DestroyImmediate(managerGO);
        }
    }
}
#endif