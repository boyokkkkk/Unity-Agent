#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;

public class LoadingSceneEventCleanupTests
{
    static readonly BindingFlags StaticFlags =
        BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public;

    static readonly BindingFlags InstanceFlags =
        BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

    static Type FindExactType(string fullName)
    {
        foreach (Assembly assembly in AppDomain.CurrentDomain.GetAssemblies())
        {
            Type[] types;
            try
            {
                types = assembly.GetTypes();
            }
            catch (ReflectionTypeLoadException error)
            {
                types = error.Types;
            }
            catch
            {
                continue;
            }

            if (types == null)
                continue;

            foreach (Type type in types)
            {
                if (type != null && type.FullName == fullName)
                    return type;
            }
        }

        return null;
    }

    static FieldInfo EventField(Type owner, string eventName)
    {
        FieldInfo field = owner.GetField(eventName, StaticFlags);
        Assert.IsNotNull(field, "Could not inspect the backing delegate for " + owner.Name + "." + eventName);
        Assert.IsTrue(
            typeof(Delegate).IsAssignableFrom(field.FieldType),
            owner.Name + "." + eventName + " is not backed by a delegate field."
        );
        return field;
    }

    static Delegate[] Handlers(FieldInfo field)
    {
        Delegate value = field.GetValue(null) as Delegate;
        return value == null ? new Delegate[0] : value.GetInvocationList();
    }

    static int Count(Delegate[] handlers, Delegate target)
    {
        int count = 0;
        foreach (Delegate handler in handlers)
        {
            if (handler.Equals(target))
                count++;
        }
        return count;
    }

    static List<Delegate> AddedHandlers(Delegate[] before, Delegate[] after)
    {
        var remaining = new List<Delegate>(after);
        foreach (Delegate original in before)
            remaining.Remove(original);
        return remaining;
    }

    static void InvokeLifecycle(Component component, string methodName)
    {
        MethodInfo method = component.GetType().GetMethod(methodName, InstanceFlags);
        Assert.IsNotNull(method, component.GetType().Name + " should define " + methodName + ".");
        method.Invoke(component, null);
    }

    static void InvokeCleanupLifecycle(Component component)
    {
        // Unity normally calls OnDisable before OnDestroy. The 2019.3 headless
        // EditMode runner does not reliably dispatch those messages for objects
        // created and destroyed within one synchronous test, so simulate that
        // lifecycle explicitly before verifying the observable event cleanup.
        MethodInfo onDisable = component.GetType().GetMethod("OnDisable", InstanceFlags);
        if (onDisable != null)
            onDisable.Invoke(component, null);

        MethodInfo onDestroy = component.GetType().GetMethod("OnDestroy", InstanceFlags);
        if (onDestroy != null)
            onDestroy.Invoke(component, null);
    }

    static void SetField(Component component, string fieldName, object value)
    {
        FieldInfo field = component.GetType().GetField(fieldName, InstanceFlags);
        Assert.IsNotNull(field, "Could not initialize " + component.GetType().Name + "." + fieldName);
        field.SetValue(component, value);
    }

    static void AssertAddedHandlersWereRemoved(
        FieldInfo field,
        Delegate[] before,
        List<Delegate> added,
        string eventLabel)
    {
        Assert.Greater(added.Count, 0, "The component did not subscribe to " + eventLabel + ".");

        Delegate[] afterDestroy = Handlers(field);
        foreach (Delegate handler in added)
        {
            Assert.That(
                Count(afterDestroy, handler),
                Is.EqualTo(Count(before, handler)),
                eventLabel + " retained a handler added by the destroyed component."
            );
        }
    }

    static void AssertComponentUnsubscribes(Type componentType, string subscriptionMethod)
    {
        Type sceneLoaderManager = FindExactType("SS3D.SceneLoaderManager");
        Type tileManager = FindExactType("SS3D.Engine.Tiles.TileManager");
        Assert.IsNotNull(sceneLoaderManager, "Could not find SS3D.SceneLoaderManager.");
        Assert.IsNotNull(tileManager, "Could not find SS3D.Engine.Tiles.TileManager.");

        FieldInfo mapLoaded = EventField(sceneLoaderManager, "mapLoaded");
        FieldInfo tileManagerLoaded = EventField(tileManager, "tileManagerLoaded");
        object originalMapHandlers = mapLoaded.GetValue(null);
        object originalTileHandlers = tileManagerLoaded.GetValue(null);

        GameObject root = null;
        try
        {
            Delegate[] mapBefore = Handlers(mapLoaded);
            Delegate[] tileBefore = Handlers(tileManagerLoaded);

            root = new GameObject(componentType.Name + "-event-cleanup-test");
            root.SetActive(false);
            Component component = root.AddComponent(componentType);

            if (componentType.FullName == "LoadingScreenManager")
            {
                Type imageType = FindExactType("UnityEngine.UI.Image");
                Assert.IsNotNull(imageType, "Could not find UnityEngine.UI.Image.");

                var imageObject = new GameObject(
                    "loading-image",
                    new[] { typeof(RectTransform), typeof(CanvasRenderer), imageType }
                );
                imageObject.transform.SetParent(root.transform);
                Component image = imageObject.GetComponent(imageType);
                SetField(component, "image", image);
                SetField(component, "wallpapers", new Sprite[1]);
            }

            root.SetActive(true);

            // Awake runs when LoadingSceneUIHelper becomes active. Start does not
            // advance automatically in an EditMode test, so invoke it when needed.
            if (AddedHandlers(mapBefore, Handlers(mapLoaded)).Count == 0 &&
                AddedHandlers(tileBefore, Handlers(tileManagerLoaded)).Count == 0)
            {
                InvokeLifecycle(component, subscriptionMethod);
            }

            List<Delegate> mapAdded = AddedHandlers(mapBefore, Handlers(mapLoaded));
            List<Delegate> tileAdded = AddedHandlers(tileBefore, Handlers(tileManagerLoaded));

            Assert.Greater(mapAdded.Count, 0, componentType.Name + " did not subscribe to mapLoaded.");
            Assert.Greater(
                tileAdded.Count,
                0,
                componentType.Name + " did not subscribe to tileManagerLoaded."
            );

            InvokeCleanupLifecycle(component);
            UnityEngine.Object.DestroyImmediate(root);
            root = null;

            AssertAddedHandlersWereRemoved(mapLoaded, mapBefore, mapAdded, "SceneLoaderManager.mapLoaded");
            AssertAddedHandlersWereRemoved(
                tileManagerLoaded,
                tileBefore,
                tileAdded,
                "TileManager.tileManagerLoaded"
            );
        }
        finally
        {
            if (root != null)
                UnityEngine.Object.DestroyImmediate(root);

            mapLoaded.SetValue(null, originalMapHandlers);
            tileManagerLoaded.SetValue(null, originalTileHandlers);
        }
    }

    [Test]
    public void LoadingScreenManager_UnsubscribesFromStaticMapEventsWhenDestroyed()
    {
        Type componentType = FindExactType("LoadingScreenManager");
        Assert.IsNotNull(componentType, "Could not find LoadingScreenManager.");
        AssertComponentUnsubscribes(componentType, "Start");
    }

    [Test]
    public void LoadingSceneUIHelper_UnsubscribesFromStaticMapEventsWhenDestroyed()
    {
        Type componentType = FindExactType("LoadingSceneUIHelper");
        Assert.IsNotNull(componentType, "Could not find LoadingSceneUIHelper.");
        AssertComponentUnsubscribes(componentType, "Awake");
    }
}
#endif
