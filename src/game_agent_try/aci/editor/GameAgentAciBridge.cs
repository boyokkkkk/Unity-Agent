using System;
using System.IO;
using System.Linq;
using System.Reflection;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

public static class GameAgentAciBridge
{
    [Serializable]
    private sealed class Request
    {
        public string operation;
        public Arguments arguments;
    }

    [Serializable]
    private sealed class Arguments
    {
        public string asset_path;
        public string name;
        public string parent_hierarchy_path;
        public string hierarchy_path;
        public string new_name;
        public string component_type;
        public int component_index;
        public string property_path;
        public string value_json;
        public string source_asset_path;
        public string source_hierarchy_path;
        public string prefab_path;
        public bool replace_existing;
        public bool force_update;
    }

    [Serializable]
    private sealed class Result
    {
        public string status;
        public string operation;
        public string asset_path;
        public string hierarchy_path;
        public string message;
        public bool refreshed;
        public bool saved;
    }

    public static void Execute()
    {
        string outputPath = CommandLineValue("-gameAgentAciOutput");
        try
        {
            string requestPath = CommandLineValue("-gameAgentAciRequest");
            Request request = JsonUtility.FromJson<Request>(File.ReadAllText(requestPath));
            if (request == null || request.arguments == null || string.IsNullOrEmpty(request.operation))
                throw new InvalidOperationException("Invalid ACI request.");
            Result result = ExecuteRequest(request);
            File.WriteAllText(outputPath, JsonUtility.ToJson(result, true));
        }
        catch (Exception ex)
        {
            File.WriteAllText(outputPath, JsonUtility.ToJson(new Result
            {
                status = "error",
                message = ex.ToString()
            }, true));
            throw;
        }
    }

    private static Result ExecuteRequest(Request request)
    {
        Arguments args = request.arguments;
        if (request.operation == "unity_asset_import")
        {
            AssetDatabase.ImportAsset(
                NormalizeAssetPath(args.asset_path),
                args.force_update ? ImportAssetOptions.ForceUpdate : ImportAssetOptions.Default);
            AssetDatabase.Refresh();
            return Success(request.operation, args.asset_path, "", false, true);
        }

        if (request.operation == "unity_prefab_create")
            return CreatePrefab(request.operation, args);

        string assetPath = NormalizeAssetPath(args.asset_path);
        bool prefab = assetPath.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase);
        bool scene = assetPath.EndsWith(".unity", StringComparison.OrdinalIgnoreCase);
        if (!prefab && !scene)
            throw new InvalidOperationException("Typed hierarchy mutations require a .unity or .prefab asset.");

        GameObject prefabRoot = null;
        Scene openedScene = default(Scene);
        try
        {
            GameObject root;
            if (prefab)
            {
                prefabRoot = PrefabUtility.LoadPrefabContents(assetPath);
                root = prefabRoot;
            }
            else
            {
                openedScene = EditorSceneManager.OpenScene(assetPath, OpenSceneMode.Single);
                root = null;
            }

            switch (request.operation)
            {
                case "unity_gameobject_create":
                    CreateGameObject(root, openedScene, args);
                    break;
                case "unity_gameobject_delete":
                    Undo.DestroyObjectImmediate(FindGameObject(root, openedScene, args.hierarchy_path));
                    break;
                case "unity_gameobject_rename":
                    Undo.RecordObject(FindGameObject(root, openedScene, args.hierarchy_path), "Game Agent Rename");
                    FindGameObject(root, openedScene, args.hierarchy_path).name = Required(args.new_name, "new_name");
                    break;
                case "unity_component_add":
                    AddComponent(FindGameObject(root, openedScene, args.hierarchy_path), args.component_type);
                    break;
                case "unity_component_remove":
                    RemoveComponent(FindGameObject(root, openedScene, args.hierarchy_path), args);
                    break;
                case "unity_serialized_property_set":
                    SetSerializedProperty(FindGameObject(root, openedScene, args.hierarchy_path), args);
                    break;
                case "unity_asset_save":
                    break;
                default:
                    throw new InvalidOperationException("Unsupported typed mutation: " + request.operation);
            }

            if (prefab)
                PrefabUtility.SaveAsPrefabAsset(prefabRoot, assetPath);
            else
                EditorSceneManager.SaveScene(openedScene, assetPath);
            AssetDatabase.SaveAssets();
            AssetDatabase.ImportAsset(assetPath, ImportAssetOptions.ForceUpdate);
            AssetDatabase.Refresh();
            return Success(request.operation, assetPath, args.hierarchy_path, true, true);
        }
        finally
        {
            if (prefabRoot != null)
                PrefabUtility.UnloadPrefabContents(prefabRoot);
        }
    }

    private static Result CreatePrefab(string operation, Arguments args)
    {
        string sourcePath = NormalizeAssetPath(args.source_asset_path);
        string destination = NormalizeAssetPath(args.prefab_path);
        if (!destination.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("prefab_path must end with .prefab");
        if (AssetDatabase.LoadAssetAtPath<GameObject>(destination) != null && !args.replace_existing)
            throw new InvalidOperationException("Prefab already exists and replace_existing is false.");
        string directory = Path.GetDirectoryName(destination);
        if (!string.IsNullOrEmpty(directory))
        {
            string absoluteDirectory = Path.Combine(
                Directory.GetParent(Application.dataPath).FullName,
                directory);
            if (!Directory.Exists(absoluteDirectory))
                Directory.CreateDirectory(absoluteDirectory);
        }

        GameObject sourceRoot = null;
        GameObject prefabContents = null;
        try
        {
            if (sourcePath.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
            {
                prefabContents = PrefabUtility.LoadPrefabContents(sourcePath);
                sourceRoot = FindUnderRoot(prefabContents, args.source_hierarchy_path);
            }
            else
            {
                Scene scene = EditorSceneManager.OpenScene(sourcePath, OpenSceneMode.Single);
                sourceRoot = FindInScene(scene, args.source_hierarchy_path);
            }
            PrefabUtility.SaveAsPrefabAsset(sourceRoot, destination);
            AssetDatabase.SaveAssets();
            AssetDatabase.ImportAsset(destination, ImportAssetOptions.ForceUpdate);
            AssetDatabase.Refresh();
            return Success(operation, destination, args.source_hierarchy_path, true, true);
        }
        finally
        {
            if (prefabContents != null)
                PrefabUtility.UnloadPrefabContents(prefabContents);
        }
    }

    private static void CreateGameObject(GameObject root, Scene scene, Arguments args)
    {
        Transform parent = null;
        if (!string.IsNullOrWhiteSpace(args.parent_hierarchy_path))
            parent = FindGameObject(root, scene, args.parent_hierarchy_path).transform;
        GameObject created = new GameObject(Required(args.name, "name"));
        Undo.RegisterCreatedObjectUndo(created, "Game Agent Create");
        if (parent != null)
            Undo.SetTransformParent(created.transform, parent, "Game Agent Parent");
        else if (root != null)
            Undo.SetTransformParent(created.transform, root.transform, "Game Agent Parent");
        else
            SceneManager.MoveGameObjectToScene(created, scene);
    }

    private static void AddComponent(GameObject gameObject, string typeName)
    {
        Type type = ResolveComponentType(typeName);
        if (gameObject.GetComponent(type) != null)
            throw new InvalidOperationException("Component already exists: " + type.FullName);
        Undo.AddComponent(gameObject, type);
    }

    private static void RemoveComponent(GameObject gameObject, Arguments args)
    {
        Type type = ResolveComponentType(args.component_type);
        Component[] matches = gameObject.GetComponents(type);
        if (args.component_index < 0 || args.component_index >= matches.Length)
            throw new InvalidOperationException("Component index is out of range.");
        Undo.DestroyObjectImmediate(matches[args.component_index]);
    }

    private static void SetSerializedProperty(GameObject gameObject, Arguments args)
    {
        Type type = ResolveComponentType(args.component_type);
        Component[] matches = gameObject.GetComponents(type);
        if (args.component_index < 0 || args.component_index >= matches.Length)
            throw new InvalidOperationException("Component index is out of range.");
        Component component = matches[args.component_index];
        Undo.RecordObject(component, "Game Agent SerializedProperty");
        SerializedObject serialized = new SerializedObject(component);
        SerializedProperty property = serialized.FindProperty(Required(args.property_path, "property_path"));
        if (property == null)
            throw new InvalidOperationException("SerializedProperty not found: " + args.property_path);
        ApplyPropertyValue(property, args.value_json);
        serialized.ApplyModifiedProperties();
        PrefabUtility.RecordPrefabInstancePropertyModifications(component);
        EditorUtility.SetDirty(component);
    }

    private static void ApplyPropertyValue(SerializedProperty property, string json)
    {
        switch (property.propertyType)
        {
            case SerializedPropertyType.Integer:
            case SerializedPropertyType.ArraySize:
            case SerializedPropertyType.LayerMask:
            case SerializedPropertyType.Enum:
                property.intValue = int.Parse(json, System.Globalization.CultureInfo.InvariantCulture);
                return;
            case SerializedPropertyType.Boolean:
                property.boolValue = bool.Parse(json);
                return;
            case SerializedPropertyType.Float:
                property.doubleValue = double.Parse(json, System.Globalization.CultureInfo.InvariantCulture);
                return;
            case SerializedPropertyType.String:
                property.stringValue = JsonString(json);
                return;
            case SerializedPropertyType.Color:
                property.colorValue = JsonUtility.FromJson<Color>(json);
                return;
            case SerializedPropertyType.Vector2:
                property.vector2Value = JsonUtility.FromJson<Vector2>(json);
                return;
            case SerializedPropertyType.Vector3:
                property.vector3Value = JsonUtility.FromJson<Vector3>(json);
                return;
            case SerializedPropertyType.Vector4:
                property.vector4Value = JsonUtility.FromJson<Vector4>(json);
                return;
            case SerializedPropertyType.ObjectReference:
                string path = JsonString(json);
                property.objectReferenceValue = string.IsNullOrEmpty(path)
                    ? null
                    : AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(NormalizeAssetPath(path));
                return;
            default:
                throw new InvalidOperationException(
                    "SerializedProperty type is not covered by the typed writer: " + property.propertyType);
        }
    }

    private static string JsonString(string json)
    {
        return JsonUtility.FromJson<StringValue>("{\"value\":" + json + "}").value;
    }

    [Serializable]
    private sealed class StringValue
    {
        public string value;
    }

    private static Type ResolveComponentType(string typeName)
    {
        string required = Required(typeName, "component_type");
        Type type = Type.GetType(required, false);
        if (type == null)
        {
            type = AppDomain.CurrentDomain.GetAssemblies()
                .SelectMany(assembly =>
                {
                    try { return assembly.GetTypes(); }
                    catch (ReflectionTypeLoadException error) { return error.Types.Where(value => value != null); }
                })
                .FirstOrDefault(value => value.FullName == required || value.Name == required);
        }
        if (type == null || !typeof(Component).IsAssignableFrom(type))
            throw new InvalidOperationException("Component type was not found: " + required);
        return type;
    }

    private static GameObject FindGameObject(GameObject root, Scene scene, string hierarchyPath)
    {
        return root != null ? FindUnderRoot(root, hierarchyPath) : FindInScene(scene, hierarchyPath);
    }

    private static GameObject FindUnderRoot(GameObject root, string hierarchyPath)
    {
        string path = Required(hierarchyPath, "hierarchy_path").Trim('/');
        if (path == root.name)
            return root;
        if (path.StartsWith(root.name + "/", StringComparison.Ordinal))
            path = path.Substring(root.name.Length + 1);
        Transform found = root.transform.Find(path);
        if (found == null)
            throw new InvalidOperationException("GameObject not found: " + hierarchyPath);
        return found.gameObject;
    }

    private static GameObject FindInScene(Scene scene, string hierarchyPath)
    {
        string path = Required(hierarchyPath, "hierarchy_path").Trim('/');
        string[] parts = path.Split('/');
        GameObject root = scene.GetRootGameObjects().FirstOrDefault(value => value.name == parts[0]);
        if (root == null)
            throw new InvalidOperationException("GameObject not found: " + hierarchyPath);
        if (parts.Length == 1)
            return root;
        Transform found = root.transform.Find(string.Join("/", parts.Skip(1).ToArray()));
        if (found == null)
            throw new InvalidOperationException("GameObject not found: " + hierarchyPath);
        return found.gameObject;
    }

    private static string NormalizeAssetPath(string value)
    {
        string path = Required(value, "asset_path").Replace('\\', '/').TrimStart('.', '/');
        if (!path.StartsWith("Assets/", StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Path must be project-relative under Assets/: " + value);
        return path;
    }

    private static string Required(string value, string name)
    {
        if (string.IsNullOrWhiteSpace(value))
            throw new InvalidOperationException(name + " must be non-empty.");
        return value;
    }

    private static string CommandLineValue(string name)
    {
        string[] args = Environment.GetCommandLineArgs();
        int index = Array.IndexOf(args, name);
        if (index < 0 || index + 1 >= args.Length)
            throw new InvalidOperationException("Missing command line argument: " + name);
        return args[index + 1];
    }

    private static Result Success(
        string operation,
        string assetPath,
        string hierarchyPath,
        bool saved,
        bool refreshed)
    {
        return new Result
        {
            status = "ok",
            operation = operation,
            asset_path = assetPath,
            hierarchy_path = hierarchyPath,
            message = "Typed Unity mutation completed.",
            saved = saved,
            refreshed = refreshed
        };
    }
}
