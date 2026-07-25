#if UNITY_EDITOR
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

public class TelescopeDynamiteBarrelZoomTests
{
    static readonly BindingFlags Flags = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

    static void SetField(object target, string name, object value)
    {
        var type = target.GetType();
        while (type != null)
        {
            var field = type.GetField(name, Flags);
            if (field != null)
            {
                field.SetValue(target, value);
                return;
            }
            type = type.BaseType;
        }
        Assert.Fail("Pipeline error: missing field " + name);
    }

    static void InvokePrivate(object target, string name)
    {
        var method = target.GetType().GetMethod(name, Flags);
        Assert.IsNotNull(method, "Pipeline error: missing method " + name);
        method.Invoke(target, null);
    }

    [Test]
    public void Telescope_OnDynamiteBarrel_DoesNotApplyScopeZoom()
    {
        var playerObject = new GameObject("player");
        var hudObject = new GameObject("hud");
        var gunObject = new GameObject("gun");
        var dynamiteObject = new GameObject("dynamite-barrel");
        var telescopeObject = new GameObject("telescope");

        try
        {
            playerObject.AddComponent<Rigidbody>();
            playerObject.AddComponent<BoxCollider>();
            var movement = playerObject.AddComponent<PlayerMovement>();
            playerObject.AddComponent<AudioSource>();
            var player = playerObject.AddComponent<PlayerManager>();
            var hud = hudObject.AddComponent<PlayerHUDController>();
            SetField(player, "hudController", hud);

            movement.ZoomFov = 50f;
            movement.LookSpeedZoom = 2f;

            var gun = gunObject.AddComponent<GunController>();
            gun.SetPlayer(player);

            dynamiteObject.transform.SetParent(gunObject.transform, false);
            dynamiteObject.AddComponent<BulletController>();
            var dynamiteBarrel = dynamiteObject.AddComponent<DynamiteBarrel>();
            Assert.IsNotNull(dynamiteBarrel, "Pipeline error: DynamiteBarrel was not attached.");
            Assert.IsNotNull(gunObject.GetComponentInChildren<DynamiteBarrel>(),
                "Pipeline error: Telescope guard cannot see the child DynamiteBarrel.");

            telescopeObject.transform.SetParent(gunObject.transform, false);
            var telescope = telescopeObject.AddComponent<Telescope>();

            Assert.DoesNotThrow(
                () => InvokePrivate(telescope, "Start"),
                "Telescope should early-return for DynamiteBarrel instead of wiring zoom/scope behavior.");

            Assert.AreEqual(50f, movement.ZoomFov, "Telescope should not change player zoom FOV for DynamiteBarrel.");
            Assert.AreEqual(2f, movement.LookSpeedZoom, "Telescope should not change player zoom speed for DynamiteBarrel.");
        }
        finally
        {
            Object.DestroyImmediate(telescopeObject);
            Object.DestroyImmediate(dynamiteObject);
            Object.DestroyImmediate(gunObject);
            Object.DestroyImmediate(hudObject);
            Object.DestroyImmediate(playerObject);
        }
    }
}
#endif