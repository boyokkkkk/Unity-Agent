using System;
using System.Collections;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.TestTools;

public class TileMapMenuSearchResetTests
{
    const BindingFlags BF = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Static;

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
                if (t != null && (t.FullName == name || t.Name == name || (t.FullName != null && t.FullName.EndsWith("." + name))))
                    return t;
        }
        return null;
    }

    static Component AddComponent(GameObject go, string fullName)
    {
        var t = FindType(fullName);
        Assert.IsNotNull(t, "Could not find component type " + fullName);
        return go.AddComponent(t);
    }

    static FieldInfo FieldUp(Type t, string name)
    {
        while (t != null) { var f = t.GetField(name, BF); if (f != null) return f; t = t.BaseType; }
        return null;
    }

    static void SetMember(object obj, string name, object value)
    {
        var f = FieldUp(obj.GetType(), name);
        if (f != null) { f.SetValue(obj, value); return; }
        var p = obj.GetType().GetProperty(name, BF);
        Assert.IsNotNull(p, "Could not find field/property " + name + " on " + obj.GetType().Name);
        p.SetValue(obj, value);
    }

    static void EnsureEmptyCollection(object obj, string fieldName)
    {
        var f = FieldUp(obj.GetType(), fieldName);
        if (f == null || f.GetValue(obj) != null) return;
        if (f.FieldType.IsArray)
            f.SetValue(obj, Array.CreateInstance(f.FieldType.GetElementType(), 0));
        else
            f.SetValue(obj, Activator.CreateInstance(f.FieldType));
    }

    static void SetText(object inputField, string val)
    {
        inputField.GetType().GetProperty("text", BF).SetValue(inputField, val);
    }

    static string GetText(object inputField)
    {
        var f = FieldUp(inputField.GetType(), "m_Text");
        if (f != null) return (string)f.GetValue(inputField);
        return (string)inputField.GetType().GetProperty("text", BF).GetValue(inputField);
    }

    [UnityTest]
    public IEnumerator ClosingTileMapMenu_ClearsSearchInputField()
    {
        LogAssert.ignoreFailingMessages = true;

        var canvasGO = new GameObject("DynamicPanelCanvas", typeof(RectTransform), typeof(Canvas), typeof(GraphicRaycaster));
        canvasGO.GetComponent<Canvas>().renderMode = RenderMode.ScreenSpaceOverlay;
        var dynamicCanvas = AddComponent(canvasGO, "DynamicPanels.DynamicPanelsCanvas");
        EnsureEmptyCollection(dynamicCanvas, "initialPanelsUnanchored");
        yield return null;

        var contentGO = new GameObject("PanelContent", typeof(RectTransform));
        contentGO.transform.SetParent(canvasGO.transform, false);
        var panelUtils = FindType("DynamicPanels.PanelUtils");
        Assert.IsNotNull(panelUtils, "Could not find DynamicPanels.PanelUtils.");
        var createPanelFor = panelUtils.GetMethod("CreatePanelFor", BF);
        var getAssociatedTab = panelUtils.GetMethod("GetAssociatedTab", BF);
        Assert.IsNotNull(createPanelFor, "Missing PanelUtils.CreatePanelFor.");
        Assert.IsNotNull(getAssociatedTab, "Missing PanelUtils.GetAssociatedTab.");
        createPanelFor.Invoke(null, new object[] { contentGO.GetComponent<RectTransform>(), dynamicCanvas });
        yield return null;
        var tab = getAssociatedTab.Invoke(null, new object[] { contentGO.GetComponent<RectTransform>() });
        Assert.IsNotNull(tab, "Failed to create a DynamicPanels tab for the menu.");

        var inputGO = new GameObject("SearchInput", typeof(RectTransform));
        inputGO.transform.SetParent(canvasGO.transform, false);
        var inputField = AddComponent(inputGO, "TMPro.TMP_InputField");
        var textGO = new GameObject("Text", typeof(RectTransform));
        textGO.transform.SetParent(inputGO.transform, false);
        var textComponent = AddComponent(textGO, "TMPro.TextMeshProUGUI");
        SetMember(inputField, "m_TextComponent", textComponent);
        yield return null;

        var hologramGO = new GameObject("ConstructionHologramManager");
        hologramGO.SetActive(false);
        var hologramManager = AddComponent(hologramGO, "SS3D.Systems.Tile.TileMapCreator.ConstructionHologramManager");

        var menuGO = new GameObject("TileMapMenu");
        menuGO.SetActive(false);
        var tileMapMenuType = FindType("TileMapMenu");
        Assert.IsNotNull(tileMapMenuType, "Could not find TileMapMenu type.");
        var menu = menuGO.AddComponent(tileMapMenuType);
        var menuRoot = new GameObject("TileMapMenuRoot");

        SetMember(menu, "_tab", tab);
        SetMember(menu, "_inputField", inputField);
        SetMember(menu, "_hologramManager", hologramManager);
        SetMember(menu, "_menuRoot", menuRoot);

        SetText(inputField, "stale search text");
        Assert.AreEqual("stale search text", GetText(inputField), "Pre-condition: search field should hold stale text.");

        var showUI = tileMapMenuType.GetMethod("ShowUI", BF);
        Assert.IsNotNull(showUI, "Could not find TileMapMenu.ShowUI(bool).");
        showUI.Invoke(menu, new object[] { false });
        yield return null;

        Assert.AreEqual(string.Empty, GetText(inputField),
            "Closing the tilemap menu should clear stale text from the search input field.");
    }
}