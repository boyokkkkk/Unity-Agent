#if UNITY_EDITOR
using System;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;
using Mirage.Sockets.Udp;

public class UdpSocketFactoryMissingNanoSocketTests
{
    static readonly BindingFlags BF =
        BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

    static void ResetInitCount()
    {
        var field = typeof(UdpSocketFactory).GetField("initCount", BF | BindingFlags.Static);
        Assert.IsNotNull(field, "Pipeline error: UdpSocketFactory.initCount not found");
        field.SetValue(null, 0);
    }

    static void InvokeAwake(UdpSocketFactory factory)
    {
        var method = typeof(UdpSocketFactory).GetMethod("Awake", BF);
        Assert.IsNotNull(method, "Pipeline error: UdpSocketFactory.Awake not found");

        try
        {
            method.Invoke(factory, null);
        }
        catch (TargetInvocationException e) when (e.InnerException != null)
        {
            throw e.InnerException;
        }
    }

    [Test]
    public void AutomaticModeFallsBackToManagedSocketWhenNanoSocketDllIsMissing()
    {
        ResetInitCount();
        var previousIgnoreFailingMessages = LogAssert.ignoreFailingMessages;
        LogAssert.ignoreFailingMessages = true;

        var go = new GameObject("UdpSocketFactory");
        go.SetActive(false);
        var factory = go.AddComponent<UdpSocketFactory>();
        factory.SocketLib = SocketLib.Automatic;

        try
        {
            Assert.DoesNotThrow(() => InvokeAwake(factory),
                "Missing NanoSockets native library should not crash UDP socket factory startup.");

            Assert.AreEqual(SocketLib.Managed, factory.SocketLib,
                "Factory should switch to managed UDP when NanoSockets cannot be loaded.");

            Assert.AreEqual("EndPointWrapper", factory.GetBindEndPoint().GetType().Name,
                "Managed fallback should use the C# UDP endpoint instead of a NanoSocket endpoint.");
        }
        finally
        {
            LogAssert.ignoreFailingMessages = previousIgnoreFailingMessages;
            UnityEngine.Object.DestroyImmediate(go);
            ResetInitCount();
        }
    }
}
#endif
