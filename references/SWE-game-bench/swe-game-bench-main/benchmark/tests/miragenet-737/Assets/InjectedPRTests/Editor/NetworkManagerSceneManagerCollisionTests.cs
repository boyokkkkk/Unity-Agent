#if UNITY_EDITOR
using System.Reflection;
using Mirage;
using NUnit.Framework;
using UnityEngine.SceneManagement;

public class NetworkManagerDerivedSceneUsage : NetworkManager
{
    public string GetActiveSceneNameFromUnitySceneManager()
    {
        return SceneManager.GetActiveScene().name;
    }
}

public class NetworkManagerSceneManagerCollisionTests
{
    [Test]
    public void DerivedNetworkManagerCanUseUnitySceneManagerWithoutNameCollision()
    {
        BindingFlags flags = BindingFlags.Instance | BindingFlags.Public;

        Assert.IsNull(typeof(NetworkManager).GetField("SceneManager", flags),
            "Mirage NetworkManager should not expose a public SceneManager field that hides UnityEngine.SceneManagement.SceneManager in derived classes.");

        Assert.IsNotNull(typeof(NetworkManager).GetField("NetworkSceneManager", flags),
            "Mirage NetworkManager should expose its network scene manager using the non-conflicting NetworkSceneManager name.");

        Assert.IsNotNull(typeof(NetworkManagerDerivedSceneUsage).GetMethod("GetActiveSceneNameFromUnitySceneManager"),
            "Pipeline error: derived NetworkManager compile regression method was not found.");
    }
}
#endif