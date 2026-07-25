#if UNITY_EDITOR
using NUnit.Framework;
using UnityEngine;
using Mirage;

public class PlayerSpawnerSceneManagerNullTests
{
    [Test]
    public void Start_WithClientSetAndSceneManagerNull_DoesNotThrow()
    {
        var prefabGO = new GameObject("PlayerPrefab");
        var playerPrefab = prefabGO.AddComponent<NetworkIdentity>();

        var clientGO = new GameObject("Client");
        var client = clientGO.AddComponent<NetworkClient>();

        var comGO = new GameObject("ClientObjectManager");
        var com = comGO.AddComponent<ClientObjectManager>();

        var spawnerGO = new GameObject("PlayerSpawner");
        var spawner = spawnerGO.AddComponent<PlayerSpawner>();
        spawner.PlayerPrefab = playerPrefab;
        spawner.Client = client;
        spawner.ClientObjectManager = com;
        // spawner.SceneManager intentionally left null — this is the bug path

        Assert.DoesNotThrow(
            () => spawner.Start(),
            "PlayerSpawner.Start() threw with SceneManager == null. " +
            "Expected null guard to be present (patched commit)."
        );

        Object.DestroyImmediate(spawnerGO);
        Object.DestroyImmediate(clientGO);
        Object.DestroyImmediate(comGO);
        Object.DestroyImmediate(prefabGO);
    }
}
#endif