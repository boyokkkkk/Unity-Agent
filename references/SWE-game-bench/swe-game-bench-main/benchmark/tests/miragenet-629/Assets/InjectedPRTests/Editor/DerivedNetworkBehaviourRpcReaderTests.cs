#if UNITY_EDITOR
using System.IO;
using System.Linq;
using Mono.Cecil;
using Mono.Cecil.Cil;
using NUnit.Framework;
using Mirage;

public class RpcDerivedNetworkBehaviour : NetworkBehaviour
{
    [ClientRpc]
    public void RpcWithDerivedBehaviour(RpcDerivedNetworkBehaviour value) { }
}

public class DerivedNetworkBehaviourRpcReaderTests
{
    [Test]
    public void GeneratedReaderForDerivedNetworkBehaviourParameter_CastsToConcreteType()
    {
        string assemblyPath = typeof(RpcDerivedNetworkBehaviour).Assembly.Location;
        if (string.IsNullOrEmpty(assemblyPath) || !File.Exists(assemblyPath))
        {
            assemblyPath = Path.Combine(
                Directory.GetCurrentDirectory(),
                "Library",
                "ScriptAssemblies",
                "InjectedPREditorTests.dll");
        }

        Assert.IsTrue(File.Exists(assemblyPath),
            "Pipeline error: compiled test assembly was not found: " + assemblyPath);

        var assembly = AssemblyDefinition.ReadAssembly(assemblyPath);
        var generated = assembly.MainModule.Types.FirstOrDefault(type =>
            type.FullName == "Mirage.GeneratedNetworkCode");

        Assert.IsNotNull(generated,
            "Pipeline error: generated Mirage network code class was not found.");

        string expectedType = typeof(RpcDerivedNetworkBehaviour).FullName;
        var reader = generated.Methods.FirstOrDefault(method =>
            method.ReturnType.FullName == expectedType &&
            method.Parameters.Count == 1 &&
            method.Parameters[0].ParameterType.Name == "NetworkReader");

        Assert.IsNotNull(reader,
            "A concrete reader should be generated for RPC parameters typed as NetworkBehaviour subclasses.");

        bool hasCastToConcreteType = reader.Body.Instructions.Any(instruction =>
            instruction.OpCode == OpCodes.Castclass &&
            instruction.Operand is TypeReference typeRef &&
            typeRef.FullName == expectedType);

        Assert.IsTrue(hasCastToConcreteType,
            "Generated reader should cast ReadNetworkBehaviour() to the concrete NetworkBehaviour subclass for IL2CPP-safe IL.");
    }
}
#endif