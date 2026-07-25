#if UNITY_EDITOR
using System;
using System.Reflection;
using System.Reflection.Emit;
using NUnit.Framework;

public class WillProcessTests
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
                if (t != null && t.FullName == fullName) return t;
        }
        return null;
    }

    static object MakeStubAssembly(string name, string[] references)
    {
        var iface = FindType("Unity.CompilationPipeline.Common.ILPostProcessing.ICompiledAssembly");
        Assert.IsNotNull(iface, "Pipeline error: ICompiledAssembly not found in loaded assemblies");

        var inMemType = iface.Assembly.GetType(
            "Unity.CompilationPipeline.Common.ILPostProcessing.InMemoryAssembly");

        var ab = AssemblyBuilder.DefineDynamicAssembly(
            new AssemblyName("WillProcessStub_" + Guid.NewGuid().ToString("N")),
            AssemblyBuilderAccess.Run);
        var mb = ab.DefineDynamicModule("M");
        var tb = mb.DefineType("StubCompiledAssembly",
            TypeAttributes.Public | TypeAttributes.Class,
            null, new[] { iface });

        var nameField = tb.DefineField("_name", typeof(string), FieldAttributes.Private);
        var refsField = tb.DefineField("_refs", typeof(string[]), FieldAttributes.Private);

        void AddGetter(string propName, Type retType, FieldBuilder field)
        {
            var m = tb.DefineMethod("get_" + propName,
                MethodAttributes.Public | MethodAttributes.Virtual |
                MethodAttributes.HideBySig | MethodAttributes.SpecialName,
                retType, Type.EmptyTypes);
            var g = m.GetILGenerator();
            if (field != null) { g.Emit(OpCodes.Ldarg_0); g.Emit(OpCodes.Ldfld, field); }
            else g.Emit(OpCodes.Ldnull);
            g.Emit(OpCodes.Ret);
            var p = tb.DefineProperty(propName, PropertyAttributes.None, retType, null);
            p.SetGetMethod(m);
        }

        AddGetter("Name", typeof(string), nameField);
        AddGetter("References", typeof(string[]), refsField);
        AddGetter("Defines", typeof(string[]), null);
        if (inMemType != null) AddGetter("InMemoryAssembly", inMemType, null);

        var ctor = tb.DefineConstructor(MethodAttributes.Public,
            CallingConventions.Standard, new[] { typeof(string), typeof(string[]) });
        var ci = ctor.GetILGenerator();
        ci.Emit(OpCodes.Ldarg_0);
        ci.Emit(OpCodes.Call, typeof(object).GetConstructor(Type.EmptyTypes));
        ci.Emit(OpCodes.Ldarg_0); ci.Emit(OpCodes.Ldarg_1); ci.Emit(OpCodes.Stfld, nameField);
        ci.Emit(OpCodes.Ldarg_0); ci.Emit(OpCodes.Ldarg_2); ci.Emit(OpCodes.Stfld, refsField);
        ci.Emit(OpCodes.Ret);

        return Activator.CreateInstance(tb.CreateType(), name, references);
    }

    [Test]
    public void WillProcess_MirrorAndMirrorEditorRefs_ReturnsTrue()
    {
        var processorType = FindType("Mirror.Weaver.MirrorILPostProcessor");
        Assert.IsNotNull(processorType, "Pipeline error: MirrorILPostProcessor not found");

        var processor = Activator.CreateInstance(processorType);
        var method = processorType.GetMethod("WillProcess", BF);
        Assert.IsNotNull(method, "Pipeline error: WillProcess method not found");

        var stub = MakeStubAssembly(
            "SomeGameAssembly",
            new[] { "/path/to/Mirror.dll", "/path/to/Mirror.Editor.dll" }
        );

        bool result = (bool)method.Invoke(processor, new object[] { stub });

        Assert.IsTrue(result,
            "Base commit bug: WillProcess returned false for assembly referencing Mirror + Mirror.Editor. " +
            "Editor check incorrectly excluded assemblies from weaving.");
    }

    [Test]
    public void WillProcess_NoMirrorRef_ReturnsFalse()
    {
        var processorType = FindType("Mirror.Weaver.MirrorILPostProcessor");
        Assert.IsNotNull(processorType, "Pipeline error: MirrorILPostProcessor not found");

        var processor = Activator.CreateInstance(processorType);
        var method = processorType.GetMethod("WillProcess", BF);

        var stub = MakeStubAssembly(
            "UnrelatedAssembly",
            new[] { "/path/to/UnityEngine.dll" }
        );

        bool result = (bool)method.Invoke(processor, new object[] { stub });
        Assert.IsFalse(result, "Sanity: no Mirror reference should return false on both commits.");
    }
}
#endif