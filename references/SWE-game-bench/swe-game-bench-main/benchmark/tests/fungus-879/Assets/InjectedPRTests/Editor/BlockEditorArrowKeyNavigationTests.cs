#if UNITY_EDITOR
using System;
using System.IO;
using System.Reflection;
using System.Text.RegularExpressions;
using NUnit.Framework;
using UnityEngine;
using Fungus;
using Fungus.EditorUtils;

// Issue #879: the command list in the Block inspector could only be navigated
// with PageUp/PageDown; the fix makes Up/Down arrow keys do the same.
//
// Real keyboard delivery is impossible in the benchmark's headless editor
// (-nographics cannot host editor views), so the fix is verified in two
// halves that together pin the behavior:
//   1. Behavioral: BlockEditor's SelectPrevious/SelectNext genuinely move the
//      flowchart's command selection (run against real objects).
//   2. Wiring: DrawButtonToolbar's source routes KeyCode.UpArrow/DownArrow
//      into that navigation (comments stripped, key reference must sit next
//      to the navigation call), and PageUp/PageDown wiring must remain.
public class BlockEditorArrowKeyNavigationTests
{
    GameObject go;
    Flowchart flowchart;
    Block block;
    Command[] commands;
    BlockEditor editor;

    [SetUp]
    public void SetUp()
    {
        go = new GameObject("BlockEditorArrowKeyNavigationTests");
        flowchart = go.AddComponent<Flowchart>();
        block = go.AddComponent<Block>();
        commands = new Command[3];
        for (int i = 0; i < commands.Length; i++)
        {
            commands[i] = go.AddComponent<Comment>();
            block.CommandList.Add(commands[i]);
        }
        flowchart.SelectedBlock = block;

        editor = UnityEditor.Editor.CreateEditor(block) as BlockEditor;
        Assert.That(editor, Is.Not.Null, "Expected UnityEditor.Editor.CreateEditor(block) to produce a BlockEditor.");
    }

    [TearDown]
    public void TearDown()
    {
        if (editor != null) UnityEngine.Object.DestroyImmediate(editor);
        if (go != null) UnityEngine.Object.DestroyImmediate(go);
    }

    // ----- behavioral half -------------------------------------------------

    void SelectOnly(Command command)
    {
        flowchart.ClearSelectedCommands();
        flowchart.AddSelectedCommand(command);
    }

    Command SingleSelectedCommand()
    {
        Assert.That(flowchart.SelectedCommands.Count, Is.EqualTo(1),
            "Expected exactly one selected command after navigation.");
        return flowchart.SelectedCommands[0];
    }

    void InvokeNavigation(string methodName)
    {
        var method = typeof(BlockEditor).GetMethod(
            methodName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
        Assert.That(method, Is.Not.Null, "BlockEditor." + methodName + " not found.");
        try
        {
            method.Invoke(editor, null);
        }
        catch (Exception)
        {
            // Repaint plumbing can complain outside a real inspector; the
            // assertions only trust the resulting selection state.
        }
    }

    [Test]
    public void SelectPrevious_MovesSelectionToPreviousCommand()
    {
        SelectOnly(commands[1]);
        InvokeNavigation("SelectPrevious");
        Assert.That(SingleSelectedCommand(), Is.SameAs(commands[0]),
            "BlockEditor.SelectPrevious() should select the previous command in the block.");
    }

    [Test]
    public void SelectNext_MovesSelectionToNextCommand()
    {
        SelectOnly(commands[1]);
        InvokeNavigation("SelectNext");
        Assert.That(SingleSelectedCommand(), Is.SameAs(commands[2]),
            "BlockEditor.SelectNext() should select the next command in the block.");
    }

    // ----- wiring half -----------------------------------------------------

    static string ToolbarSourceBody()
    {
        var path = Path.GetFullPath(Path.Combine(Application.dataPath, "Fungus/Scripts/Editor/BlockEditor.cs"));
        Assert.That(File.Exists(path), Is.True, "Missing script at: " + path);
        var source = File.ReadAllText(path);
        source = Regex.Replace(source, @"/\*.*?\*/", "", RegexOptions.Singleline);
        source = Regex.Replace(source, @"//[^\n]*", "");
        return MethodBody(source, "DrawButtonToolbar");
    }

    static string MethodBody(string source, string methodName)
    {
        var match = Regex.Match(source, @"void\s+" + methodName + @"\s*\(\s*\)");
        Assert.That(match.Success, Is.True, "Could not find method " + methodName + ".");
        int braceStart = source.IndexOf('{', match.Index);
        Assert.That(braceStart, Is.GreaterThan(-1), "Could not find body of " + methodName + ".");
        int depth = 0;
        for (int i = braceStart; i < source.Length; i++)
        {
            if (source[i] == '{')
            {
                depth++;
            }
            else if (source[i] == '}')
            {
                depth--;
                if (depth == 0)
                {
                    return source.Substring(braceStart, i - braceStart + 1);
                }
            }
        }
        Assert.Fail("Unbalanced braces in " + methodName + ".");
        return null;
    }

    static void AssertKeyWiredToNavigation(string body, string keyName, string navigationCall)
    {
        int index = body.IndexOf("KeyCode." + keyName, StringComparison.Ordinal);
        Assert.That(index, Is.GreaterThanOrEqualTo(0),
            "DrawButtonToolbar does not handle KeyCode." + keyName + ".");
        var window = body.Substring(index, Math.Min(body.Length - index, 600));
        Assert.That(window.Contains(navigationCall + "("), Is.True,
            "KeyCode." + keyName + " is not routed to " + navigationCall + "() in DrawButtonToolbar.");
    }

    [Test]
    public void UpArrow_IsWiredToPreviousCommandNavigation()
    {
        AssertKeyWiredToNavigation(ToolbarSourceBody(), "UpArrow", "SelectPrevious");
    }

    [Test]
    public void DownArrow_IsWiredToNextCommandNavigation()
    {
        AssertKeyWiredToNavigation(ToolbarSourceBody(), "DownArrow", "SelectNext");
    }

    [Test]
    public void PageUpAndPageDown_WiringStillPresent()
    {
        var body = ToolbarSourceBody();
        AssertKeyWiredToNavigation(body, "PageUp", "SelectPrevious");
        AssertKeyWiredToNavigation(body, "PageDown", "SelectNext");
    }
}
#endif
