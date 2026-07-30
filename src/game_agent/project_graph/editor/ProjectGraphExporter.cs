#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using UnityEditor;
using UnityEditor.Events;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.SceneManagement;

public static class GameAgentProjectGraphExporter
{
    private const string SchemaVersion = "game-agent-unity-editor-export-v1";

    [Serializable]
    private sealed class ExportDocument
    {
        public string schema_version = SchemaVersion;
        public string unity_version;
        public List<AssetRecord> assets = new List<AssetRecord>();
        public List<GameObjectRecord> game_objects = new List<GameObjectRecord>();
        public List<ComponentRecord> components = new List<ComponentRecord>();
        public List<ReferenceRecord> serialized_refs = new List<ReferenceRecord>();
        public List<UnityEventRecord> unity_event_calls = new List<UnityEventRecord>();
        public List<PrefabSourceRecord> prefab_sources = new List<PrefabSourceRecord>();
    }

    [Serializable]
    private sealed class AssetRecord
    {
        public string id;
        public string kind;
        public string name;
        public string path;
        public string guid;
    }

    [Serializable]
    private sealed class GameObjectRecord
    {
        public string id;
        public string name;
        public string asset_id;
        public string asset_path;
        public string hierarchy_path;
        public string parent_id;
        public bool active;
        public string tag;
        public int layer;
    }

    [Serializable]
    private sealed class ComponentRecord
    {
        public string id;
        public string name;
        public string game_object_id;
        public string asset_path;
        public string type_name;
        public string assembly_name;
        public string script_path;
        public string script_guid;
        public bool enabled;
    }

    [Serializable]
    private sealed class ReferenceRecord
    {
        public string source_component_id;
        public string source_type;
        public string property_path;
        public string target_id;
        public string target_kind;
        public string target_path;
    }

    [Serializable]
    private sealed class UnityEventRecord
    {
        public string source_component_id;
        public string event_field;
        public string target_id;
        public string target_type;
        public string method_name;
        public int listener_index;
    }

    [Serializable]
    private sealed class PrefabSourceRecord
    {
        public string game_object_id;
        public string prefab_id;
        public string prefab_path;
    }

    private sealed class ExportContext
    {
        public readonly ExportDocument Document = new ExportDocument();
        public readonly HashSet<string> AssetIds = new HashSet<string>(StringComparer.Ordinal);
        public readonly HashSet<string> GameObjectIds = new HashSet<string>(StringComparer.Ordinal);
        public readonly HashSet<string> ComponentIds = new HashSet<string>(StringComparer.Ordinal);
        public readonly HashSet<string> ReferenceKeys = new HashSet<string>(StringComparer.Ordinal);
        public readonly HashSet<string> EventKeys = new HashSet<string>(StringComparer.Ordinal);
        public readonly HashSet<string> PrefabKeys = new HashSet<string>(StringComparer.Ordinal);
    }

    public static void Export()
    {
        string outputPath = GetArgument("-gameAgentGraphOutput");
        if (string.IsNullOrWhiteSpace(outputPath))
            throw new ArgumentException("Missing -gameAgentGraphOutput <path>");

        var context = new ExportContext();
        context.Document.unity_version = Application.unityVersion;
        ExportScenes(context);
        ExportPrefabs(context);
        ExportRemainingAssets(context);
        Sort(context.Document);

        string fullPath = Path.GetFullPath(outputPath);
        Directory.CreateDirectory(Path.GetDirectoryName(fullPath));
        File.WriteAllText(fullPath, JsonUtility.ToJson(context.Document, true), new UTF8Encoding(false));
        Debug.Log(
            "GAME_AGENT_GRAPH_EXPORT_OK " +
            JsonUtility.ToJson(new ExportSummary(context.Document))
        );
    }

    [Serializable]
    private sealed class ExportSummary
    {
        public int assets;
        public int game_objects;
        public int components;
        public int serialized_refs;
        public int unity_event_calls;
        public int prefab_sources;

        public ExportSummary(ExportDocument document)
        {
            assets = document.assets.Count;
            game_objects = document.game_objects.Count;
            components = document.components.Count;
            serialized_refs = document.serialized_refs.Count;
            unity_event_calls = document.unity_event_calls.Count;
            prefab_sources = document.prefab_sources.Count;
        }
    }

    private static void ExportScenes(ExportContext context)
    {
        foreach (string guid in AssetDatabase.FindAssets("t:Scene", new[] { "Assets" }).OrderBy(value => value))
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            string assetId = AddAsset(context, path, "SCENE");
            Scene scene = EditorSceneManager.OpenScene(path, OpenSceneMode.Single);
            foreach (GameObject root in scene.GetRootGameObjects().OrderBy(item => item.name))
                ExportGameObject(context, root, assetId, path, null);
        }
    }

    private static void ExportPrefabs(ExportContext context)
    {
        foreach (string guid in AssetDatabase.FindAssets("t:Prefab", new[] { "Assets" }).OrderBy(value => value))
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            string assetId = AddAsset(context, path, "PREFAB");
            GameObject root = PrefabUtility.LoadPrefabContents(path);
            try
            {
                ExportGameObject(context, root, assetId, path, null);
            }
            finally
            {
                PrefabUtility.UnloadPrefabContents(root);
            }
        }
    }

    private static void ExportRemainingAssets(ExportContext context)
    {
        foreach (string guid in AssetDatabase.FindAssets("", new[] { "Assets" }).OrderBy(value => value))
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            if (Directory.Exists(path) || path.EndsWith(".cs", StringComparison.OrdinalIgnoreCase))
                continue;
            AddAsset(context, path, AssetKind(path));
        }
    }

    private static string AddAsset(ExportContext context, string path, string kind)
    {
        string guid = AssetDatabase.AssetPathToGUID(path);
        string id = "unity-asset:" + guid;
        if (context.AssetIds.Add(id))
        {
            context.Document.assets.Add(new AssetRecord
            {
                id = id,
                kind = kind,
                name = Path.GetFileNameWithoutExtension(path),
                path = path.Replace('\\', '/'),
                guid = guid,
            });
        }
        return id;
    }

    private static string AssetKind(string path)
    {
        string extension = Path.GetExtension(path).ToLowerInvariant();
        if (extension == ".unity") return "SCENE";
        if (extension == ".prefab") return "PREFAB";
        return "ASSET";
    }

    private static void ExportGameObject(
        ExportContext context,
        GameObject gameObject,
        string assetId,
        string assetPath,
        string parentId)
    {
        string gameObjectId = ObjectId(gameObject, assetPath, HierarchyPath(gameObject.transform));
        if (context.GameObjectIds.Add(gameObjectId))
        {
            context.Document.game_objects.Add(new GameObjectRecord
            {
                id = gameObjectId,
                name = gameObject.name,
                asset_id = assetId,
                asset_path = assetPath,
                hierarchy_path = HierarchyPath(gameObject.transform),
                parent_id = parentId ?? "",
                active = gameObject.activeSelf,
                tag = SafeTag(gameObject),
                layer = gameObject.layer,
            });
        }

        string prefabPath = PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(gameObject);
        if (!string.IsNullOrWhiteSpace(prefabPath)
            && !string.Equals(prefabPath, assetPath, StringComparison.OrdinalIgnoreCase))
        {
            string prefabId = AddAsset(context, prefabPath, "PREFAB");
            string key = gameObjectId + "\u001f" + prefabId;
            if (context.PrefabKeys.Add(key))
                context.Document.prefab_sources.Add(new PrefabSourceRecord
                {
                    game_object_id = gameObjectId,
                    prefab_id = prefabId,
                    prefab_path = prefabPath,
                });
        }

        foreach (Component component in gameObject.GetComponents<Component>())
        {
            if (component == null)
                continue;
            ExportComponent(context, component, gameObjectId, assetPath);
        }

        foreach (Transform child in gameObject.transform.Cast<Transform>().OrderBy(item => item.GetSiblingIndex()))
            ExportGameObject(context, child.gameObject, assetId, assetPath, gameObjectId);
    }

    private static void ExportComponent(
        ExportContext context,
        Component component,
        string gameObjectId,
        string assetPath)
    {
        Type type = component.GetType();
        string componentId = ObjectId(component, assetPath, HierarchyPath(component.transform) + ":" + type.FullName);
        MonoScript script = component is MonoBehaviour behaviour
            ? MonoScript.FromMonoBehaviour(behaviour)
            : null;
        string scriptPath = script == null ? "" : AssetDatabase.GetAssetPath(script);
        string scriptGuid = string.IsNullOrEmpty(scriptPath) ? "" : AssetDatabase.AssetPathToGUID(scriptPath);
        bool enabled = !(component is Behaviour stateful) || stateful.enabled;
        if (context.ComponentIds.Add(componentId))
        {
            context.Document.components.Add(new ComponentRecord
            {
                id = componentId,
                name = type.Name,
                game_object_id = gameObjectId,
                asset_path = assetPath,
                type_name = type.FullName ?? type.Name,
                assembly_name = type.Assembly.GetName().Name,
                script_path = scriptPath,
                script_guid = scriptGuid,
                enabled = enabled,
            });
        }
        ExportSerializedReferences(context, component, componentId, type.FullName ?? type.Name);
        ExportUnityEvents(context, component, componentId);
    }

    private static void ExportSerializedReferences(
        ExportContext context,
        Component component,
        string componentId,
        string sourceType)
    {
        SerializedObject serialized;
        try
        {
            serialized = new SerializedObject(component);
        }
        catch
        {
            return;
        }
        SerializedProperty iterator = serialized.GetIterator();
        bool enterChildren = true;
        while (iterator.Next(enterChildren))
        {
            enterChildren = true;
            if (iterator.propertyType != SerializedPropertyType.ObjectReference
                || iterator.propertyPath == "m_Script")
                continue;
            UnityEngine.Object target = iterator.objectReferenceValue;
            if (target == null)
                continue;
            string targetPath;
            string targetKind;
            string targetId = EnsureObject(context, target, out targetKind, out targetPath);
            if (string.IsNullOrEmpty(targetId))
                continue;
            string key = componentId + "\u001f" + iterator.propertyPath + "\u001f" + targetId;
            if (context.ReferenceKeys.Add(key))
                context.Document.serialized_refs.Add(new ReferenceRecord
                {
                    source_component_id = componentId,
                    source_type = sourceType,
                    property_path = iterator.propertyPath,
                    target_id = targetId,
                    target_kind = targetKind,
                    target_path = targetPath,
                });
        }
    }

    private static void ExportUnityEvents(ExportContext context, Component component, string componentId)
    {
        for (Type current = component.GetType(); current != null && current != typeof(object); current = current.BaseType)
        {
            foreach (FieldInfo field in current.GetFields(
                         BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
            {
                if (!typeof(UnityEventBase).IsAssignableFrom(field.FieldType))
                    continue;
                UnityEventBase unityEvent;
                try
                {
                    unityEvent = field.GetValue(component) as UnityEventBase;
                }
                catch
                {
                    continue;
                }
                if (unityEvent == null)
                    continue;
                for (int index = 0; index < unityEvent.GetPersistentEventCount(); index++)
                {
                    UnityEngine.Object target = unityEvent.GetPersistentTarget(index);
                    string method = unityEvent.GetPersistentMethodName(index);
                    if (target == null || string.IsNullOrWhiteSpace(method))
                        continue;
                    string targetPath;
                    string targetKind;
                    string targetId = EnsureObject(context, target, out targetKind, out targetPath);
                    string key = componentId + "\u001f" + field.Name + "\u001f" + index + "\u001f" + targetId + "\u001f" + method;
                    if (context.EventKeys.Add(key))
                        context.Document.unity_event_calls.Add(new UnityEventRecord
                        {
                            source_component_id = componentId,
                            event_field = field.Name,
                            target_id = targetId,
                            target_type = target.GetType().FullName ?? target.GetType().Name,
                            method_name = method,
                            listener_index = index,
                        });
                }
            }
        }
    }

    private static string EnsureObject(
        ExportContext context,
        UnityEngine.Object target,
        out string kind,
        out string path)
    {
        path = AssetDatabase.GetAssetPath(target).Replace('\\', '/');
        if (target is GameObject gameObject)
        {
            kind = "GAME_OBJECT";
            return ObjectId(gameObject, path, HierarchyPath(gameObject.transform));
        }
        if (target is Component component)
        {
            kind = "COMPONENT";
            return ObjectId(component, path, HierarchyPath(component.transform) + ":" + component.GetType().FullName);
        }
        if (!string.IsNullOrEmpty(path))
        {
            kind = AssetKind(path);
            return AddAsset(context, path, kind);
        }
        kind = "ASSET";
        return ObjectId(target, "", target.name);
    }

    private static string ObjectId(UnityEngine.Object value, string assetPath, string fallback)
    {
        GlobalObjectId global = GlobalObjectId.GetGlobalObjectIdSlow(value);
        string text = global.ToString();
        if (!string.IsNullOrWhiteSpace(text) && !text.EndsWith("-0-0", StringComparison.Ordinal))
            return "unity-object:" + text;
        return "unity-object:fallback:" + Sha256(assetPath + "\u001f" + fallback);
    }

    private static string Sha256(string text)
    {
        using (SHA256 sha = SHA256.Create())
            return string.Concat(sha.ComputeHash(Encoding.UTF8.GetBytes(text)).Select(value => value.ToString("x2"))).Substring(0, 20);
    }

    private static string HierarchyPath(Transform transform)
    {
        var parts = new List<string>();
        for (Transform current = transform; current != null; current = current.parent)
            parts.Add(current.name);
        parts.Reverse();
        return string.Join("/", parts);
    }

    private static string SafeTag(GameObject gameObject)
    {
        try { return gameObject.tag; }
        catch { return ""; }
    }

    private static string GetArgument(string name)
    {
        string[] values = Environment.GetCommandLineArgs();
        for (int index = 0; index < values.Length - 1; index++)
            if (string.Equals(values[index], name, StringComparison.OrdinalIgnoreCase))
                return values[index + 1];
        return "";
    }

    private static void Sort(ExportDocument document)
    {
        document.assets = document.assets.OrderBy(item => item.id).ToList();
        document.game_objects = document.game_objects.OrderBy(item => item.id).ToList();
        document.components = document.components.OrderBy(item => item.id).ToList();
        document.serialized_refs = document.serialized_refs
            .OrderBy(item => item.source_component_id).ThenBy(item => item.property_path).ThenBy(item => item.target_id).ToList();
        document.unity_event_calls = document.unity_event_calls
            .OrderBy(item => item.source_component_id).ThenBy(item => item.event_field).ThenBy(item => item.listener_index).ToList();
        document.prefab_sources = document.prefab_sources
            .OrderBy(item => item.game_object_id).ThenBy(item => item.prefab_id).ToList();
    }
}
#endif
