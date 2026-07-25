using System;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

public class PxTextureFormatTests
{
    static readonly BindingFlags BF =
        BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;

    static Type FindType(string fullName)
    {
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            Type[] types;
            try { types = asm.GetTypes(); }
            catch (ReflectionTypeLoadException e) { types = e.Types; }
            catch { continue; }
            if (types == null) continue;
            foreach (var t in types)
                if (t != null && t.FullName == fullName) return t;
        }
        return null;
    }

    [Test]
    public void AsUnityTextureFormat_B8G8R8A8_ReturnsRGBA32()
    {
        var extType = FindType("GVR.Phoenix.Util.PxTextureDataExtension");
        Assert.IsNotNull(extType, "Pipeline error: PxTextureDataExtension type not found");

        var method = extType.GetMethod("AsUnityTextureFormat", BF);
        Assert.IsNotNull(method, "Pipeline error: AsUnityTextureFormat method not found");

        // Get PxTexture.Format enum via reflection — no compile-time PxCs reference needed
        var formatType = FindType("PxCs.Interface.PxTexture+Format");
        Assert.IsNotNull(formatType, "Pipeline error: PxTexture.Format enum not found");

        // Base:    returns TextureFormat.Alpha8  (wrong — loses RGB channels)
        // Patched: returns TextureFormat.RGBA32  (correct)
        var b8g8r8a8 = Enum.Parse(formatType, "tex_B8G8R8A8");
        var result = (TextureFormat)method.Invoke(null, new object[] { b8g8r8a8 });

        Assert.AreEqual(TextureFormat.RGBA32, result,
            "Base commit bug: tex_B8G8R8A8 mapped to Alpha8 instead of RGBA32.");
    }
}