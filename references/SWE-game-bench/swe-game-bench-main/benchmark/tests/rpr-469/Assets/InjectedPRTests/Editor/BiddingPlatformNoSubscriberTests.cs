#if UNITY_EDITOR
using System.Reflection;
using NUnit.Framework;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

public class BiddingPlatformNoSubscriberTests
{
    static readonly BindingFlags Flags = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

    static void SetField(object target, string name, object value)
    {
        var field = target.GetType().GetField(name, Flags);
        Assert.IsNotNull(field, "Pipeline error: missing field " + name);
        field.SetValue(target, value);
    }

    static TextMeshProUGUI TextField(string name)
    {
        return new GameObject(name).AddComponent<TextMeshProUGUI>();
    }

    [Test]
    public void SetItem_WithoutOnItemSetSubscriber_DoesNotThrow()
    {
        var root = new GameObject("bidding-platform");
        root.SetActive(false);

        var itemPrefab = new GameObject("dummy-augment");
        itemPrefab.AddComponent<GunBody>();
        var holder = new GameObject("model-holder");
        var description = new GameObject("description");
        var radial = new GameObject("radial").AddComponent<Image>();
        var symbol = new GameObject("symbol").AddComponent<Image>();
        var shader = Shader.Find("Sprites/Default") ?? Shader.Find("UI/Default") ?? Shader.Find("Standard");
        radial.material = new Material(shader);

        try
        {
            root.AddComponent<MeshRenderer>().material = new Material(Shader.Find("Standard"));
            root.AddComponent<BoxCollider>();
            var timer = root.AddComponent<Timer>();
            var platform = root.AddComponent<BiddingPlatform>();

            holder.transform.SetParent(root.transform);
            description.transform.SetParent(root.transform);

            SetField(platform, "itemNameText", TextField("name-text"));
            SetField(platform, "itemDescriptionText", TextField("description-text"));
            SetField(platform, "itemCostText", TextField("cost-text"));
            SetField(platform, "timerText", TextField("timer-text"));
            SetField(platform, "modelHolder", holder);
            SetField(platform, "description", description);
            SetField(platform, "radialUI", radial);
            SetField(platform, "augmentSymbol", symbol);
            SetField(platform, "auctionTimer", timer);

            root.SetActive(true);

            var item = ScriptableObject.CreateInstance<Item>();
            item.displayName = "Test item";
            item.displayDescription = "Test description";
            item.augmentType = AugmentType.Body;
            item.augment = itemPrefab;

            Assert.DoesNotThrow(
                () => platform.SetItem(item),
                "SetItem should allow no onItemSet subscribers. The old code called onItemSet.Invoke(this) and crashed.");
        }
        finally
        {
            Object.DestroyImmediate(itemPrefab);
            Object.DestroyImmediate(root);
            Object.DestroyImmediate(holder);
            Object.DestroyImmediate(description);
            Object.DestroyImmediate(radial.gameObject);
            Object.DestroyImmediate(symbol.gameObject);
        }
    }
}
#endif