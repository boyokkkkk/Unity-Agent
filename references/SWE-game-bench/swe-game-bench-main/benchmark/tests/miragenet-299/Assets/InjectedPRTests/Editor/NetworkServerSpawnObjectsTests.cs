#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using NUnit.Framework;
using UnityEngine;
using Mirror;

public class PipelineListenTransport : Transport
{
    public int listenCalls;
    readonly TaskCompletionSource<IConnection> pendingAccept = new TaskCompletionSource<IConnection>();

    public override IEnumerable<string> Scheme
    {
        get { return new[] { "pipeline" }; }
    }

    public override bool Supported
    {
        get { return true; }
    }

    public override Task ListenAsync()
    {
        listenCalls++;
        return Task.FromResult(0);
    }

    public override void Disconnect()
    {
        pendingAccept.TrySetResult(null);
    }

    public override Task<IConnection> ConnectAsync(Uri uri)
    {
        return Task.FromResult<IConnection>(null);
    }

    public override Task<IConnection> AcceptAsync()
    {
        return pendingAccept.Task;
    }

    public override IEnumerable<Uri> ServerUri()
    {
        return new[] { new Uri("pipeline://localhost") };
    }
}

public class NetworkServerSpawnObjectsTests
{
    [Test]
    public void ListenAsync_SpawnsSceneObjectsWithoutNetworkManager()
    {
        var serverGO = new GameObject("NetworkServer");
        var sceneObjectGO = new GameObject("SceneObject");

        try
        {
            var transport = serverGO.AddComponent<PipelineListenTransport>();
            var server = serverGO.AddComponent<NetworkServer>();
            server.transport = transport;

            var identity = sceneObjectGO.AddComponent<NetworkIdentity>();
            identity.sceneId = 0xAABBCCDDUL;
            sceneObjectGO.SetActive(false);

            server.ListenAsync().GetAwaiter().GetResult();

            Assert.AreEqual(1, transport.listenCalls, "Sanity: fake transport should start listening once.");
            Assert.IsTrue(server.Active, "Sanity: NetworkServer should be active after ListenAsync.");
            Assert.AreNotEqual(0u, identity.NetId,
                "NetworkServer.ListenAsync should spawn scene NetworkIdentity objects without NetworkManager.");
            Assert.AreSame(server, identity.Server,
                "Spawned scene identity should be owned by the NetworkServer that started listening.");
            Assert.IsTrue(server.spawned.ContainsKey(identity.NetId),
                "Spawned scene identity should be registered in NetworkServer.spawned.");
        }
        finally
        {
            var server = serverGO.GetComponent<NetworkServer>();
            if (server != null && server.transport != null)
            {
                server.transport.Disconnect();
            }

            UnityEngine.Object.DestroyImmediate(sceneObjectGO);
            UnityEngine.Object.DestroyImmediate(serverGO);
        }
    }
}
#endif