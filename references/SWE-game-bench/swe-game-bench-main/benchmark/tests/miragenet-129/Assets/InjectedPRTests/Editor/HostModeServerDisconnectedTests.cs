#if UNITY_EDITOR
using System;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;
using Mirror;

public class HostModeServerDisconnectedTests
{
    static readonly BindingFlags BF =
        BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

    [Test]
    public void ClientDisconnect_InHostMode_RaisesServerDisconnectedEvent()
    {
        var serverGO = new GameObject("NetworkServer");
        var server = serverGO.AddComponent<NetworkServer>();

        var clientGO = new GameObject("NetworkClient");
        var client = clientGO.AddComponent<NetworkClient>();

        // Wire host-mode: NetworkClient.hostServer (private field) = server
        // so isLocalClient => (hostServer != null) is true.
        var hostServerField = typeof(NetworkClient).GetField("hostServer", BF);
        Assert.IsNotNull(hostServerField, "Pipeline error: NetworkClient.hostServer field not found");
        hostServerField.SetValue(client, server);

        // Put client in Connected state via internal NetworkClient.connectState
        // so isConnected => (connectState == Connected) is true.
        var connectStateField = typeof(NetworkClient).GetField("connectState", BF);
        Assert.IsNotNull(connectStateField, "Pipeline error: NetworkClient.connectState field not found");
        var connectStateType = connectStateField.FieldType;
        connectStateField.SetValue(client, Enum.Parse(connectStateType, "Connected"));

        Assert.IsTrue(client.isLocalClient,
            "Pipeline error: isLocalClient should be true after wiring hostServer");
        Assert.IsTrue(client.isConnected,
            "Pipeline error: isConnected should be true after setting connectState=Connected");

        bool serverDisconnectedFired = false;
        server.Disconnected.AddListener(_ => { serverDisconnectedFired = true; });

        // Cleanup after the event fires may throw without a real Transport; not under test.
        try { client.Disconnect(); }
        catch { }

        Assert.IsTrue(
            serverDisconnectedFired,
            "Base commit bug: server.Disconnected never raised on host-mode client disconnect. " +
            "NetworkClient.Disconnect() set connectState=Disconnected before entering the host-mode branch, " +
            "so the isConnected guard short-circuited hostServer.Disconnected.Invoke()."
        );

        UnityEngine.Object.DestroyImmediate(clientGO);
        UnityEngine.Object.DestroyImmediate(serverGO);
    }
}
#endif