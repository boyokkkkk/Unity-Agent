#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.Reflection;
using System.Threading.Tasks;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.Events;
using Mirror;

public class CountingTransport : Transport
{
    public int clientDisconnectCalls;

    public override bool Available() { return true; }
    public override bool ClientConnected() { return true; }
    public override Task ClientConnectAsync(string address) { return Task.FromResult(0); }
    public override bool ClientSend(int channelId, ArraySegment<byte> segment) { return true; }

    public override void ClientDisconnect()
    {
        clientDisconnectCalls++;
        OnClientDisconnected.Invoke();
    }

    public override Uri ServerUri() { return new Uri("tcp://localhost"); }
    public override bool ServerActive() { return true; }
    public override void ServerStart() { }
    public override bool ServerSend(List<int> connectionIds, int channelId, ArraySegment<byte> segment) { return true; }
    public override void ServerDisconnect(int connectionId) { }
    public override string ServerGetClientAddress(int connectionId) { return "localhost"; }
    public override void ServerStop() { }
    public override void Shutdown() { }
    public override int GetMaxPacketSize(int channelId = Channels.DefaultReliable) { return 1200; }
}

public class ClientDisconnectSingleCallbackTests
{
    static readonly BindingFlags BF =
        BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

    static void SetProperty(object target, string name, object value)
    {
        var property = target.GetType().GetProperty(name, BF);
        Assert.IsNotNull(property, "Pipeline error: property not found: " + name);
        var setter = property.GetSetMethod(true);
        Assert.IsNotNull(setter, "Pipeline error: property has no setter: " + name);
        setter.Invoke(target, new object[] { value });
    }

    [Test]
    public void NetworkConnectionToServerDisconnect_RaisesClientDisconnectedOnce()
    {
        var transportGO = new GameObject("CountingTransport");
        var transport = transportGO.AddComponent<CountingTransport>();
        Transport.activeTransport = transport;

        var clientGO = new GameObject("NetworkClient");
        var client = clientGO.AddComponent<NetworkClient>();

        var identityGO = new GameObject("NetworkIdentity");
        var identity = identityGO.AddComponent<NetworkIdentity>();

        var connection = new NetworkConnectionToServer();
        SetProperty(connection, "identity", identity);
        SetProperty(identity, "client", client);
        SetProperty(client, "connection", connection);

        var onDisconnected = typeof(NetworkClient).GetMethod("OnDisconnected", BF);
        Assert.IsNotNull(onDisconnected, "Pipeline error: NetworkClient.OnDisconnected not found");
        var handler = (UnityAction)Delegate.CreateDelegate(typeof(UnityAction), client, onDisconnected);
        transport.OnClientDisconnected.AddListener(handler);

        int disconnectedEvents = 0;
        client.Disconnected.AddListener(() => { disconnectedEvents++; });

        connection.Disconnect();

        Assert.AreEqual(1, transport.clientDisconnectCalls,
            "Sanity: transport disconnect should be requested once.");
        Assert.AreEqual(1, disconnectedEvents,
            "Client-side disconnect callback should fire exactly once for one disconnect.");

        Transport.activeTransport = null;
        UnityEngine.Object.DestroyImmediate(identityGO);
        UnityEngine.Object.DestroyImmediate(clientGO);
        UnityEngine.Object.DestroyImmediate(transportGO);
    }
}
#endif