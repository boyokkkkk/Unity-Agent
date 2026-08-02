using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

static string StableId(string ns, params string[] parts)
{
    var normalized = string.Join("\u001f", parts.Select(p => p.Replace('\\', '/')));
    var bytes = SHA256.HashData(Encoding.UTF8.GetBytes(ns + "\u001e" + normalized));
    return $"{ns}:{Convert.ToHexString(bytes).ToLowerInvariant()[..20]}";
}

static string RelativePath(string root, string path) =>
    Path.GetRelativePath(root, path).Replace('\\', '/');

static string NamespaceOf(SyntaxNode node)
{
    var names = node.Ancestors()
        .OfType<BaseNamespaceDeclarationSyntax>()
        .Reverse()
        .Select(item => item.Name.ToString());
    return string.Join(".", names);
}

static string TypeName(TypeDeclarationSyntax type)
{
    var containers = type.Ancestors()
        .OfType<TypeDeclarationSyntax>()
        .Reverse()
        .Select(item => item.Identifier.ValueText)
        .Append(type.Identifier.ValueText);
    var nested = string.Join(".", containers);
    var ns = NamespaceOf(type);
    return string.IsNullOrWhiteSpace(ns) ? nested : ns + "." + nested;
}

static Dictionary<string, object?> Attrs(params (string Key, object? Value)[] values) =>
    values.ToDictionary(item => item.Key, item => item.Value);

static string ExpressionName(ExpressionSyntax expression) => expression switch
{
    IdentifierNameSyntax identifier => identifier.Identifier.ValueText,
    MemberAccessExpressionSyntax member => member.Name.Identifier.ValueText,
    MemberBindingExpressionSyntax binding => binding.Name.Identifier.ValueText,
    _ => expression.ToString().Split('.').LastOrDefault() ?? expression.ToString(),
};

if (args.Length == 1 && args[0] == "--validate-stdin")
{
    var source = Console.In.ReadToEnd();
    var tree = CSharpSyntaxTree.ParseText(
        source,
        new CSharpParseOptions(LanguageVersion.Latest)
    );
    var diagnostics = tree.GetDiagnostics()
        .Where(item => item.Severity == DiagnosticSeverity.Error)
        .Select(item =>
        {
            var position = item.Location.GetLineSpan().StartLinePosition;
            return new
            {
                id = item.Id,
                severity = item.Severity.ToString().ToLowerInvariant(),
                message = item.GetMessage(),
                line = position.Line + 1,
                column = position.Character + 1,
            };
        })
        .ToList();
    Console.WriteLine(JsonSerializer.Serialize(new
    {
        status = diagnostics.Count == 0 ? "valid" : "invalid",
        diagnostics,
    }));
    return diagnostics.Count == 0 ? 0 : 4;
}

if (args.Length != 4 || args[0] != "--project" || args[2] != "--output")
{
    Console.Error.WriteLine("Usage: RoslynProjectGraph --project <UnityProject> --output <graph.json> | --validate-stdin");
    return 2;
}

var project = Path.GetFullPath(args[1]);
var output = Path.GetFullPath(args[3]);
var assets = Path.Combine(project, "Assets");
if (!Directory.Exists(assets))
{
    Console.Error.WriteLine($"Assets directory not found: {assets}");
    return 3;
}

var nodes = new Dictionary<string, Dictionary<string, object?>>();
var edges = new List<Dictionary<string, object?>>();
var edgeKeys = new HashSet<string>();
var methodIdsByName = new Dictionary<string, List<string>>(StringComparer.Ordinal);
var methodIdsByTypeAndName = new Dictionary<(string Type, string Name), List<string>>();
var pendingCalls = new List<(string Source, string Name, int Arity, string Expression, int Line)>();
var fieldIdsByTypeAndName = new Dictionary<(string Type, string Name), string>();
var fieldTypesByTypeAndName = new Dictionary<(string Type, string Name), string>();
var eventIdsByTypeAndName = new Dictionary<(string Type, string Name), string>();
var eventIdsByName = new Dictionary<string, List<string>>(StringComparer.Ordinal);
var pendingUnityEvents = new List<(string Source, string TargetName, string EventExpression, int Line)>();
var pendingEventSubscriptions = new List<(string Registrar, string SubscriberType, string HandlerName, string EventOwnerType, string EventName, string Expression, int Line)>();
var pendingEventTriggers = new List<(string Publisher, string DeclaringType, string EventName, string Expression, int Line)>();

void AddNode(string id, string kind, string name, string path, Dictionary<string, object?> attributes)
{
    nodes[id] = new()
    {
        ["id"] = id, ["kind"] = kind, ["name"] = name, ["path"] = path,
        ["attributes"] = attributes,
    };
}

void AddEdge(string source, string target, string kind, Dictionary<string, object?> attributes)
{
    var attrs = JsonSerializer.Serialize(attributes);
    if (edgeKeys.Add($"{source}\u001f{target}\u001f{kind}\u001f{attrs}"))
        edges.Add(new()
        {
            ["source"] = source, ["target"] = target, ["kind"] = kind,
            ["attributes"] = attributes,
        });
}

foreach (var file in Directory.EnumerateFiles(assets, "*.cs", SearchOption.AllDirectories)
             .OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
{
    var relative = RelativePath(project, file);
    var source = File.ReadAllText(file);
    var tree = CSharpSyntaxTree.ParseText(source, path: relative);
    var root = tree.GetCompilationUnitRoot();
    var fileId = StableId("cs-file", relative);
    AddNode(fileId, "CSHARP_FILE", Path.GetFileName(file), relative,
        Attrs(("parser", "roslyn"), ("language", "csharp")));

    foreach (var type in root.DescendantNodes().OfType<TypeDeclarationSyntax>())
    {
        var fullName = TypeName(type);
        var bases = type.BaseList?.Types.Select(item => item.Type.ToString()).ToArray()
                    ?? Array.Empty<string>();
        var isMono = bases.Any(item =>
            item.EndsWith("MonoBehaviour", StringComparison.Ordinal)
            || item.EndsWith("ScriptableObject", StringComparison.Ordinal));
        var typeId = StableId("cs-type", fullName);
        AddNode(typeId, isMono ? "MONO_BEHAVIOUR" : "CLASS", fullName, relative,
            Attrs(
                ("file_id", fileId),
                ("namespace", NamespaceOf(type)),
                ("bases", bases),
                ("declaration_kind", type.Kind().ToString())
            ));

        foreach (var field in type.Members.OfType<FieldDeclarationSyntax>())
        {
            var attributes = field.AttributeLists.SelectMany(list => list.Attributes)
                .Select(attribute => attribute.Name.ToString()).ToArray();
            var serialized = attributes.Any(name =>
                name.EndsWith("SerializeField", StringComparison.Ordinal)
                || name.EndsWith("SerializeReference", StringComparison.Ordinal))
                || field.Modifiers.Any(SyntaxKind.PublicKeyword);
            foreach (var variable in field.Declaration.Variables)
            {
                var fieldId = StableId("cs-field", fullName, variable.Identifier.ValueText);
                AddNode(fieldId, "FIELD", variable.Identifier.ValueText, relative,
                    Attrs(
                        ("declaring_type", fullName),
                        ("declaring_type_id", typeId),
                        ("field_type", field.Declaration.Type.ToString()),
                        ("serialized", serialized),
                        ("attributes", attributes)
                    ));
                fieldIdsByTypeAndName[(fullName, variable.Identifier.ValueText)] = fieldId;
                fieldTypesByTypeAndName[(fullName, variable.Identifier.ValueText)] = field.Declaration.Type.ToString();
            }
        }

        foreach (var eventField in type.Members.OfType<EventFieldDeclarationSyntax>())
        {
            foreach (var variable in eventField.Declaration.Variables)
            {
                var eventName = variable.Identifier.ValueText;
                var eventId = StableId("cs-field", fullName, eventName);
                AddNode(eventId, "FIELD", eventName, relative,
                    Attrs(
                        ("declaring_type", fullName),
                        ("declaring_type_id", typeId),
                        ("field_type", eventField.Declaration.Type.ToString()),
                        ("serialized", false),
                        ("is_event", true)
                    ));
                fieldIdsByTypeAndName[(fullName, eventName)] = eventId;
                eventIdsByTypeAndName[(fullName, eventName)] = eventId;
                eventIdsByTypeAndName[(fullName.Split('.').Last(), eventName)] = eventId;
                if (!eventIdsByName.TryGetValue(eventName, out var declarations))
                    eventIdsByName[eventName] = declarations = new();
                declarations.Add(eventId);
            }
        }

        foreach (var method in type.Members.OfType<MethodDeclarationSyntax>())
        {
            var methodName = method.Identifier.ValueText;
            var arity = method.ParameterList.Parameters.Count;
            var methodId = StableId("cs-method", fullName, methodName, arity.ToString());
            AddNode(methodId, "METHOD", methodName, relative,
                Attrs(
                    ("declaring_type", fullName),
                    ("declaring_type_id", typeId),
                    ("arity", arity),
                    ("return_type", method.ReturnType.ToString()),
                    ("line", tree.GetLineSpan(method.Span).StartLinePosition.Line + 1)
                ));
            if (!methodIdsByName.TryGetValue(methodName, out var overloads))
                methodIdsByName[methodName] = overloads = new();
            overloads.Add(methodId);
            if (!methodIdsByTypeAndName.TryGetValue((fullName, methodName), out var typedOverloads))
                methodIdsByTypeAndName[(fullName, methodName)] = typedOverloads = new();
            typedOverloads.Add(methodId);

            foreach (var assignment in method.DescendantNodes().OfType<AssignmentExpressionSyntax>())
            {
                var leftName = ExpressionName(assignment.Left);
                var line = tree.GetLineSpan(assignment.Span).StartLinePosition.Line + 1;
                if (assignment.IsKind(SyntaxKind.AddAssignmentExpression))
                {
                    var handlerName = ExpressionName(assignment.Right);
                    var ownerRoot = assignment.Left is MemberAccessExpressionSyntax member
                        ? member.Expression.ToString().Split('.')[0]
                        : fullName;
                    var eventOwnerType = fieldTypesByTypeAndName.TryGetValue((fullName, ownerRoot), out var fieldType)
                        ? fieldType
                        : ownerRoot;
                    pendingEventSubscriptions.Add((
                        methodId,
                        fullName,
                        handlerName,
                        eventOwnerType,
                        leftName,
                        assignment.ToString(),
                        line
                    ));
                    continue;
                }
                if (fieldIdsByTypeAndName.TryGetValue((fullName, leftName), out var writtenField))
                    AddEdge(methodId, writtenField, "WRITES_STATE",
                        Attrs(
                            ("expression", assignment.ToString()),
                            ("operation", assignment.OperatorToken.ValueText),
                            ("line", line)
                        ));
            }

            foreach (var call in method.DescendantNodes().OfType<InvocationExpressionSyntax>())
            {
                var calledName = call.Expression switch
                {
                    IdentifierNameSyntax identifier => identifier.Identifier.ValueText,
                    MemberAccessExpressionSyntax member => member.Name.Identifier.ValueText,
                    MemberBindingExpressionSyntax binding => binding.Name.Identifier.ValueText,
                    _ => call.Expression.ToString(),
                };
                pendingCalls.Add((
                    methodId,
                    calledName,
                    call.ArgumentList.Arguments.Count,
                    call.Expression.ToString(),
                    tree.GetLineSpan(call.Span).StartLinePosition.Line + 1
                ));
                if (calledName == "Invoke")
                {
                    string eventName = call.Expression switch
                    {
                        MemberAccessExpressionSyntax member => ExpressionName(member.Expression),
                        MemberBindingExpressionSyntax => call.Ancestors()
                            .OfType<ConditionalAccessExpressionSyntax>()
                            .Select(item => ExpressionName(item.Expression))
                            .FirstOrDefault() ?? "",
                        _ => "",
                    };
                    if (!string.IsNullOrWhiteSpace(eventName))
                        pendingEventTriggers.Add((
                            methodId,
                            fullName,
                            eventName,
                            call.Parent is ConditionalAccessExpressionSyntax conditional
                                ? conditional.ToString()
                                : call.ToString(),
                            tree.GetLineSpan(call.Span).StartLinePosition.Line + 1
                        ));
                }
                if (call.Expression is MemberAccessExpressionSyntax addListener
                    && addListener.Name.Identifier.ValueText == "AddListener"
                    && call.ArgumentList.Arguments.Count > 0)
                {
                    string eventExpression = addListener.Expression.ToString();
                    string rootName = eventExpression.Split('.')[0];
                    string eventSource = fieldIdsByTypeAndName.TryGetValue((fullName, rootName), out var fieldSource)
                        ? fieldSource : methodId;
                    ExpressionSyntax listener = call.ArgumentList.Arguments[0].Expression;
                    IEnumerable<InvocationExpressionSyntax> listenerCalls = listener switch
                    {
                        ParenthesizedLambdaExpressionSyntax lambda => lambda.Body.DescendantNodesAndSelf().OfType<InvocationExpressionSyntax>(),
                        SimpleLambdaExpressionSyntax lambda => lambda.Body.DescendantNodesAndSelf().OfType<InvocationExpressionSyntax>(),
                        _ => Enumerable.Empty<InvocationExpressionSyntax>(),
                    };
                    var targets = listenerCalls.Select(item => item.Expression switch
                    {
                        IdentifierNameSyntax identifier => identifier.Identifier.ValueText,
                        MemberAccessExpressionSyntax member => member.Name.Identifier.ValueText,
                        MemberBindingExpressionSyntax binding => binding.Name.Identifier.ValueText,
                        _ => item.Expression.ToString(),
                    }).ToList();
                    if (listener is IdentifierNameSyntax methodGroup)
                        targets.Add(methodGroup.Identifier.ValueText);
                    else if (listener is MemberAccessExpressionSyntax memberGroup)
                        targets.Add(memberGroup.Name.Identifier.ValueText);
                    foreach (string targetName in targets.Distinct(StringComparer.Ordinal))
                        pendingUnityEvents.Add((
                            eventSource,
                            targetName,
                            eventExpression,
                            tree.GetLineSpan(call.Span).StartLinePosition.Line + 1
                        ));
                }
            }
        }
    }
}

foreach (var subscription in pendingEventSubscriptions)
{
    List<string> events;
    if (!string.IsNullOrWhiteSpace(subscription.EventOwnerType)
        && eventIdsByTypeAndName.TryGetValue((subscription.EventOwnerType, subscription.EventName), out var ownedEvent))
        events = new() { ownedEvent };
    else
    {
        if (!eventIdsByName.TryGetValue(subscription.EventName, out var namedEvents))
            continue;
        events = namedEvents;
    }
    List<string> handlers;
    if (methodIdsByTypeAndName.TryGetValue((subscription.SubscriberType, subscription.HandlerName), out var typedHandlers))
        handlers = typedHandlers;
    else
    {
        if (!methodIdsByName.TryGetValue(subscription.HandlerName, out var namedHandlers))
            continue;
        handlers = namedHandlers;
    }
    foreach (var handler in handlers)
    foreach (var eventId in events)
        AddEdge(handler, eventId, "SUBSCRIBES_TO",
            Attrs(
                ("registrar_method_id", subscription.Registrar),
                ("expression", subscription.Expression),
                ("line", subscription.Line),
                ("resolution", handlers.Count == 1 && events.Count == 1 ? "unique" : "name")
            ));
}

foreach (var trigger in pendingEventTriggers)
{
    var targets = eventIdsByTypeAndName.TryGetValue((trigger.DeclaringType, trigger.EventName), out var localEvent)
        ? new List<string> { localEvent }
        : eventIdsByName.GetValueOrDefault(trigger.EventName, new List<string>());
    foreach (var eventId in targets)
        AddEdge(trigger.Publisher, eventId, "PUBLISHES_EVENT",
            Attrs(
                ("expression", trigger.Expression),
                ("line", trigger.Line),
                ("resolution", targets.Count == 1 ? "unique" : "name")
            ));
}

foreach (var call in pendingCalls)
{
    if (!methodIdsByName.TryGetValue(call.Name, out var candidates))
        continue;
    var matching = candidates.Where(id =>
        Convert.ToInt32(nodes[id]["attributes"] is Dictionary<string, object?> attrs
            ? attrs["arity"] : -1) == call.Arity).ToList();
    if (matching.Count == 0)
        matching = candidates;
    foreach (var target in matching)
        AddEdge(call.Source, target, "CALLS",
            Attrs(("expression", call.Expression), ("line", call.Line), ("resolution", matching.Count == 1 ? "unique" : "name")));
}

foreach (var binding in pendingUnityEvents)
{
    if (!methodIdsByName.TryGetValue(binding.TargetName, out var candidates))
        continue;
    foreach (var target in candidates)
        AddEdge(binding.Source, target, "UNITY_EVENT_CALL",
            Attrs(
                ("event_expression", binding.EventExpression),
                ("line", binding.Line),
                ("binding", "dynamic_add_listener"),
                ("resolution", candidates.Count == 1 ? "unique" : "name")
            ));
}

var payload = new Dictionary<string, object?>
{
    ["schema_version"] = "game-agent-unity-project-graph-v1",
    ["project_path"] = project,
    ["metadata"] = Attrs(
        ("code_parser", "roslyn"),
        ("roslyn_version", typeof(CSharpSyntaxTree).Assembly.GetName().Version?.ToString())
    ),
    ["nodes"] = nodes.Values.OrderBy(node => node["id"]).ToList(),
    ["edges"] = edges.OrderBy(edge => edge["kind"]).ThenBy(edge => edge["source"]).ThenBy(edge => edge["target"]).ToList(),
};
Directory.CreateDirectory(Path.GetDirectoryName(output)!);
File.WriteAllText(output, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
Console.WriteLine(JsonSerializer.Serialize(new { files = nodes.Values.Count(n => Equals(n["kind"], "CSHARP_FILE")), nodes = nodes.Count, edges = edges.Count }));
return 0;
