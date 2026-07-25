#if UNITY_EDITOR
using System;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.InputSystem;

public class CameraSnapDirectionTests
{
    static BindingFlags BF = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

    static Type FindType(string name)
    {
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            Type[] types;
            try { types = asm.GetTypes(); }
            catch (ReflectionTypeLoadException e) { types = e.Types; }
            catch { continue; }
            if (types == null) continue;
            foreach (var t in types)
                if (t != null && (t.Name == name || (t.FullName != null && t.FullName.EndsWith("." + name))))
                    return t;
        }
        return null;
    }

    static float ReadHorizontalAngle(object camera, Type cameraType)
    {
        var field = cameraType.GetField("_horizontalAngle", BF);
        Assert.IsNotNull(field, "Could not find _horizontalAngle field");
        return (float)field.GetValue(camera);
    }

    static void SetHorizontalAngle(object camera, Type cameraType, float value)
    {
        var field = cameraType.GetField("_horizontalAngle", BF);
        Assert.IsNotNull(field, "Could not find _horizontalAngle field");
        field.SetValue(camera, value);
    }

    static void InvokeHandler(object camera, Type cameraType, string methodName)
    {
        var method = cameraType.GetMethod(methodName, BF);
        Assert.IsNotNull(method, "Could not find " + methodName);
        method.Invoke(camera, new object[] { default(InputAction.CallbackContext) });
    }

    [Test]
    public void SnapLeftAndRight_FollowTheirButtonDirections()
    {
        var cameraType = FindType("CameraFollow");
        Assert.IsNotNull(cameraType, "Could not find CameraFollow type");

        var go = new GameObject("CameraFollow_Test");
        var camera = go.AddComponent(cameraType);

        SetHorizontalAngle(camera, cameraType, 0f);
        InvokeHandler(camera, cameraType, "HandleSnapLeft");
        var leftAngle = ReadHorizontalAngle(camera, cameraType);
        Assert.Less(Mathf.Abs(Mathf.DeltaAngle(90f, leftAngle)), 0.01f,
            "Base commit bug: snap-left rotated to the right/opposite direction.");

        SetHorizontalAngle(camera, cameraType, 0f);
        InvokeHandler(camera, cameraType, "HandleSnapRight");
        var rightAngle = ReadHorizontalAngle(camera, cameraType);
        Assert.Less(Mathf.Abs(Mathf.DeltaAngle(-90f, rightAngle)), 0.01f,
            "Base commit bug: snap-right rotated to the left/opposite direction.");

        UnityEngine.Object.DestroyImmediate(go);
    }
}
#endif