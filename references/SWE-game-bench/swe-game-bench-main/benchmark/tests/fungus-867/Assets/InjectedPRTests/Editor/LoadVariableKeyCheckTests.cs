#if UNITY_EDITOR
using NUnit.Framework;
using System.Reflection;
using UnityEngine;
using Fungus;

public class LoadVariableKeyCheckTests
{
    static void SetInstanceField(object obj, string fieldName, object value)
    {
        var f = obj.GetType().GetField(fieldName,
            BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public);
        Assert.NotNull(f, $"Missing field '{fieldName}' on {obj.GetType()}");
        f.SetValue(obj, value);
    }

    static string GetSaveProfilePrefixOrEmpty()
    {
        var t    = typeof(SetSaveProfile);
        var prop = t.GetProperty("SaveProfile", BindingFlags.Static | BindingFlags.Public);
        if (prop != null && prop.PropertyType == typeof(string))
            return (string)prop.GetValue(null, null) ?? "";
        var field = t.GetField("SaveProfile", BindingFlags.Static | BindingFlags.Public);
        if (field != null && field.FieldType == typeof(string))
            return (string)field.GetValue(null) ?? "";
        return "";
    }

    [Test]
    public void OnEnter_DoesNotModifyVariable_WhenPrefsKeyMissing()
    {
        var go       = new GameObject("test_go");
        var flowchart = go.AddComponent<Flowchart>();
        var cmd      = go.AddComponent<LoadVariable>();
        var intVar   = go.AddComponent<IntegerVariable>();
        intVar.Key   = "TestInt";
        intVar.Value = 12345;

        string key      = "DefinitelyMissingKey_UnitTest_872";
        string prefix   = GetSaveProfilePrefixOrEmpty();
        string prefsKey = prefix + "_" + key;
        PlayerPrefs.DeleteKey(prefsKey);
        PlayerPrefs.Save();

        SetInstanceField(cmd, "key",      key);
        SetInstanceField(cmd, "variable", intVar);
        cmd.OnEnter();

        Assert.AreEqual(12345, intVar.Value,
            "Variable changed even though PlayerPrefs key is missing.");
    }
}
#endif
