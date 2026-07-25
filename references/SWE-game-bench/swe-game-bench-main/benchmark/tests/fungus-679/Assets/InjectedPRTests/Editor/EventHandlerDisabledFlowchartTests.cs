#if UNITY_EDITOR
using System.Reflection;
using NUnit.Framework;
using UnityEngine;
using Fungus;
using FungusEventHandler = Fungus.EventHandler;

public class EventHandlerDisabledFlowchartTests
{
    static readonly BindingFlags AnyInstance = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;

    static void SetMember(object target, string name, object value)
    {
        var type = target.GetType();

        var property = type.GetProperty(name, AnyInstance);
        if (property != null)
        {
            var setMethod = property.GetSetMethod(true);
            if (setMethod != null)
            {
                setMethod.Invoke(target, new[] { value });
                return;
            }
        }

        var field = type.GetField(name, AnyInstance);
        if (field != null)
        {
            field.SetValue(target, value);
            return;
        }

        Assert.Fail("Could not find writable member '" + name + "' on " + type.FullName);
    }

    static object GetMember(object target, string name)
    {
        var type = target.GetType();

        var property = type.GetProperty(name, AnyInstance);
        if (property != null)
        {
            var getMethod = property.GetGetMethod(true);
            if (getMethod != null)
            {
                return getMethod.Invoke(target, null);
            }
        }

        var field = type.GetField(name, AnyInstance);
        if (field != null)
        {
            return field.GetValue(target);
        }

        Assert.Fail("Could not find readable member '" + name + "' on " + type.FullName);
        return null;
    }

    [Test]
    public void ExecuteBlock_DisabledFlowchart_DoesNotAutoSelectParentBlock()
    {
        var go = new GameObject("EventHandlerDisabledFlowchartTest");

        try
        {
            var flowchart = go.AddComponent<Flowchart>();
            var block = go.AddComponent<Block>();
            var handler = go.AddComponent<FungusEventHandler>();

            handler.ParentBlock = block;
            SetMember(block, "_EventHandler", handler);
            SetMember(flowchart, "SelectedBlock", null);

            Assert.That(flowchart.isActiveAndEnabled, Is.True, "Flowchart should begin enabled for the test setup.");

            flowchart.enabled = false;
            Assert.That(flowchart.isActiveAndEnabled, Is.False, "Flowchart must be disabled for this regression check.");

            var executed = handler.ExecuteBlock();

            Assert.That(executed, Is.False, "Disabled flowcharts should not execute event handlers.");
            Assert.That(GetMember(flowchart, "SelectedBlock"), Is.Null,
                "Disabled flowcharts should not auto-select the parent block.");
        }
        finally
        {
            Object.DestroyImmediate(go);
        }
    }
}
#endif
