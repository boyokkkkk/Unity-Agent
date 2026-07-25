#if UNITY_EDITOR
using System;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

public class MarkupIsOkTests
{
    static readonly BindingFlags BF =
        BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

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
                if (t != null && t.Name == name) return t;
        }
        return null;
    }

    [Test]
    public void MarkupIsOk_MismatchedTagTypes_ReturnsFalse()
    {
        var chatType = FindType("InRoomChat");
        Assert.IsNotNull(chatType, "Pipeline error: InRoomChat type not found");

        var go = new GameObject("InRoomChat");
        var chat = go.AddComponent(chatType);
        Assert.IsNotNull(chat, "Pipeline error: Could not AddComponent InRoomChat");

        var method = chatType.GetMethod("MarkupIsOk", BF);
        Assert.IsNotNull(method, "Pipeline error: MarkupIsOk method not found");

        var result = (bool)method.Invoke(chat, new object[] { "<bold>\n<italic>text</bold></bold>" });
        Assert.IsFalse(result, "MarkupIsOk should reject mismatched tag types.");

        var validResult = (bool)method.Invoke(chat, new object[] { "<bold>text</bold>" });
        Assert.IsTrue(validResult, "Correctly matched tags should return true.");

        UnityEngine.Object.DestroyImmediate(go);
    }
}
#endif