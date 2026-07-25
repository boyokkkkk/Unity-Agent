#if UNITY_EDITOR
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

public class RubberSniperCrosshairResetTests
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
    public void OnDestroy_ResetsRubberSniperCrosshairOffset()
    {
        var hudRoot = new GameObject("hud-root", typeof(RectTransform));
        var crosshairObject = new GameObject("crosshair", typeof(RectTransform));
        var playerObject = new GameObject("player");
        var gunObject = new GameObject("gun");
        var sniperObject = new GameObject("rubber-sniper");

        try
        {
            var hudRootRect = hudRoot.GetComponent<RectTransform>();
            hudRootRect.sizeDelta = new Vector2(200f, 100f);
            var crosshair = crosshairObject.GetComponent<RectTransform>();
            crosshairObject.transform.SetParent(hudRoot.transform, false);

            var hud = hudRoot.AddComponent<PlayerHUDController>();
            SetField(hud, "hud", hudRootRect);
            SetField(hud, "crosshair", crosshair);

            hud.MoveCrosshair(0.5f, -0.5f);
            Assert.AreNotEqual(Vector2.zero, crosshair.anchoredPosition, "Test setup should move the crosshair away from center.");

            playerObject.AddComponent<Rigidbody>();
            playerObject.AddComponent<BoxCollider>();
            playerObject.AddComponent<PlayerMovement>();
            playerObject.AddComponent<AudioSource>();
            var player = playerObject.AddComponent<PlayerManager>();
            SetField(player, "hudController", hud);

            var gun = gunObject.AddComponent<GunController>();
            gun.SetPlayer(player);

            sniperObject.SetActive(false);
            sniperObject.transform.SetParent(gunObject.transform, false);
            var sniper = sniperObject.AddComponent<RubberSniper>();
            SetField(sniper, "gunController", gun);

            InvokePrivate(sniper, "OnDestroy");

            Assert.AreEqual(
                Vector2.zero,
                crosshair.anchoredPosition,
                "Destroying RubberSniper should restore the HUD crosshair to the default center position.");
        }
        finally
        {
            Object.DestroyImmediate(sniperObject);
            Object.DestroyImmediate(gunObject);
            Object.DestroyImmediate(playerObject);
            Object.DestroyImmediate(crosshairObject);
            Object.DestroyImmediate(hudRoot);
        }
    }
}
#endif