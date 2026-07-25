#if UNITY_EDITOR
using System;
using System.Reflection;
using NUnit.Framework;

public class InteractInHandTests
{
    static readonly BindingFlags BF =
        BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

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
                if (t != null && t.FullName == fullName)
                    return t;
        }
        return null;
    }

    static bool CallsMethod(MethodInfo caller, MethodInfo expectedCallee)
    {
        var body = caller.GetMethodBody();
        Assert.IsNotNull(body, "Pipeline error: method has no body.");

        var il = body.GetILAsByteArray();
        var module = caller.Module;

        for (int i = 0; i < il.Length; i++)
        {
            byte opcode = il[i];
            if (opcode == 0x28 || opcode == 0x6F)
            {
                int token = BitConverter.ToInt32(il, i + 1);
                MethodBase resolved = null;
                try { resolved = module.ResolveMethod(token); } catch { }

                if (resolved == expectedCallee)
                    return true;

                i += 4;
            }
        }

        return false;
    }

    [Test]
    public void InteractInHand_IsPublic_ForInventoryAccess()
    {
        var controllerType = FindType("SS3D.Systems.Interactions.InteractionController");
        Assert.IsNotNull(controllerType, "Pipeline error: Missing InteractionController");

        var publicMethod = controllerType.GetMethod("InteractInHand", BindingFlags.Instance | BindingFlags.Public);

        Assert.IsNotNull(publicMethod, "Base commit bug: InteractInHand is private! The inventory cannot cross-call it to trigger active hand clicks.");
    }

    [Test]
    public void ContainerSlotInteraction_CallsInteractInHand()
    {
        var controllerType = FindType("SS3D.Systems.Interactions.InteractionController");
        var inventoryType = FindType("SS3D.Systems.Inventory.Containers.HumanInventory");
        Assert.IsNotNull(controllerType, "Pipeline error: Missing InteractionController");
        Assert.IsNotNull(inventoryType, "Pipeline error: Missing HumanInventory");

        var interactInHand = controllerType.GetMethod("InteractInHand", BF);
        var interactWithSlot = inventoryType.GetMethod("ClientInteractWithContainerSlot", BF);
        Assert.IsNotNull(interactInHand, "Pipeline error: Missing InteractInHand");
        Assert.IsNotNull(interactWithSlot, "Pipeline error: Missing ClientInteractWithContainerSlot");

        Assert.IsTrue(
            CallsMethod(interactWithSlot, interactInHand),
            "Clicking an occupied selected-hand slot does not route to InteractInHand.");
    }
}
#endif
