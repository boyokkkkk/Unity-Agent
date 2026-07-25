#if UNITY_EDITOR
using System;
using System.Reflection;
using System.Runtime.Serialization;
using NUnit.Framework;
using UnityEngine;

public class CommandListAdaptorNegativeRectTests
{
    static Type FindType(string fullName)
    {
        foreach (var a in AppDomain.CurrentDomain.GetAssemblies())
        {
            try { var t = a.GetType(fullName, false); if (t != null) return t; }
            catch { }
        }
        return null;
    }

    [Test]
    public void DrawHeader_And_DrawItem_NegativeWidth_DoNotThrow()
    {
        var t = FindType("Fungus.EditorUtils.CommandListAdaptor");
        Assert.That(t, Is.Not.Null, "Could not find Fungus.EditorUtils.CommandListAdaptor.");

        var adaptor  = FormatterServices.GetUninitializedObject(t);
        var drawItem = t.GetMethod("DrawItem", BindingFlags.Instance | BindingFlags.Public);
        Assert.That(drawItem, Is.Not.Null);

        Assert.DoesNotThrow(() =>
        {
            drawItem.Invoke(adaptor, new object[] { new Rect(0, 0, -1, 16), 0, false, false });
        });

        var drawHeader = t.GetMethod("DrawHeader", BindingFlags.Instance | BindingFlags.NonPublic);
        Assert.That(drawHeader, Is.Not.Null);

        Assert.DoesNotThrow(() =>
        {
            drawHeader.Invoke(adaptor, new object[] { new Rect(0, 0, -1, 16) });
        });
    }
}
#endif
