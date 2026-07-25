#if UNITY_EDITOR
using NUnit.Framework;
using System.IO;
using System.Text.RegularExpressions;
using UnityEngine;

public class HierarchyIconsPlacementTests_PR800
{
    static string ScriptPath()
    {
        return Path.GetFullPath(Path.Combine(Application.dataPath, "Fungus/Scripts/Editor/HierarchyIcons.cs"));
    }

    static string ReadScript()
    {
        var path = ScriptPath();
        Assert.That(File.Exists(path), Is.True, $"Missing script at: {path}");
        return File.ReadAllText(path);
    }

    [Test]
    public void Unity2019Plus_HierarchyIconRectX_NotShiftedLeft()
    {
#if UNITY_2019_1_OR_NEWER
        var text = ReadScript();

        // The buggy line must not appear anywhere in the file.
        Assert.That(Regex.IsMatch(text, @"\br\.x\s*-=\s*r\.height\s*;"), Is.False,
            "Buggy x-offset 'r.x -= r.height;' still present.");

        // Whether the 2019 #if block was kept or removed, r.x must be assigned
        // a non-negative-shift value somewhere in the DrawIcon method.
        var drawIcon = Regex.Match(text,
            @"void\s+DrawIcon\b(?<body>[\s\S]*?)^\s*\}",
            RegexOptions.Multiline);
        Assert.That(drawIcon.Success, Is.True, "Could not find DrawIcon method body.");
        var body = drawIcon.Groups["body"].Value;

        Assert.That(Regex.IsMatch(body, @"\br\.x\s*=\s*"), Is.True,
            "Expected r.x to be directly assigned a value in DrawIcon.");
#else
        Assert.Ignore("Only applicable to UNITY_2019_1_OR_NEWER.");
#endif
    }
}
#endif
