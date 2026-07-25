#if UNITY_EDITOR
using System;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

public class ItemPickupIconTests
{
    static BindingFlags BF = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

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

    static Type FindComponentType(string fullName)
    {
        var type = FindType(fullName);
        return type != null && typeof(Component).IsAssignableFrom(type) ? type : null;
    }

    static Sprite CreateSprite(string name)
    {
        var texture = new Texture2D(2, 2);
        var sprite = Sprite.Create(texture, new Rect(0, 0, 2, 2), new Vector2(0.5f, 0.5f));
        sprite.name = name;
        return sprite;
    }

    [Test]
    public void CreateTargetInteractions_PickupInteractionUsesDefaultPickupIcon()
    {
        var itemType = FindComponentType("SS3D.Systems.Storage.Items.Item");
        Assert.IsNotNull(itemType, "Could not find Item type.");

        var itemGO = new GameObject("PickupIconItem");
        var item = itemGO.AddComponent(itemType);
        var itemSprite = CreateSprite("ItemSpecificSprite");

        var spriteField = itemType.GetField("_sprite", BF);
        Assert.IsNotNull(spriteField, "Could not find Item._sprite field.");
        spriteField.SetValue(item, itemSprite);

        var createTargetInteractions = itemType.GetMethod("CreateTargetInteractions", BF);
        Assert.IsNotNull(createTargetInteractions, "Could not find Item.CreateTargetInteractions.");

        var interactions = createTargetInteractions.Invoke(item, new object[] { null }) as Array;
        Assert.IsNotNull(interactions, "CreateTargetInteractions should return an interaction array.");
        Assert.Greater(interactions.Length, 0, "CreateTargetInteractions should include a pickup interaction.");

        object pickupInteraction = null;
        foreach (var interaction in interactions)
        {
            if (interaction != null && interaction.GetType().FullName == "SS3D.Systems.Storage.Interactions.PickupInteraction")
            {
                pickupInteraction = interaction;
                break;
            }
        }

        Assert.IsNotNull(pickupInteraction, "Could not find PickupInteraction in target interactions.");

        var iconMember = pickupInteraction.GetType().GetProperty("Icon", BF) as MemberInfo
            ?? pickupInteraction.GetType().GetField("Icon", BF);
        Assert.IsNotNull(iconMember, "Could not find PickupInteraction.Icon.");

        object icon = iconMember is PropertyInfo property
            ? property.GetValue(pickupInteraction, null)
            : ((FieldInfo)iconMember).GetValue(pickupInteraction);

        Assert.IsNull(icon, "Base commit bug: pickup interaction used the item sprite instead of the default pickup icon.");

        UnityEngine.Object.DestroyImmediate(itemGO);
        UnityEngine.Object.DestroyImmediate(itemSprite.texture);
        UnityEngine.Object.DestroyImmediate(itemSprite);
    }
}
#endif