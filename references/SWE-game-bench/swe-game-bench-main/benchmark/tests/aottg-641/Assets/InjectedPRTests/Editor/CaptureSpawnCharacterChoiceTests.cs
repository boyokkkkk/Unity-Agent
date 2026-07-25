#if UNITY_EDITOR
using System;
using System.Reflection;
using NUnit.Framework;

public class CaptureSpawnCharacterChoiceTests
{
    static readonly BindingFlags BF =
        BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Static;

    static Type FindType(string name)
    {
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            Type[] types;
            try { types = asm.GetTypes(); }
            catch (ReflectionTypeLoadException e) { types = e.Types; }
            catch { continue; }
            if (types == null) continue;
            foreach (var t in types)
                if (t != null && (t.Name == name || (t.FullName != null && t.FullName.EndsWith("." + name))))
                    return t;
        }
        return null;
    }

    static int CountCallsTo(MethodInfo caller, Type declaringType, string methodName)
    {
        var body = caller.GetMethodBody();
        Assert.IsNotNull(body, "Pipeline error: method has no body.");

        int count = 0;
        var il = body.GetILAsByteArray();
        var module = caller.Module;

        for (int i = 0; i < il.Length; i++)
        {
            var opcode = il[i];
            if (opcode == 0x28 || opcode == 0x6F)
            {
                int token = BitConverter.ToInt32(il, i + 1);
                MethodBase resolved = null;
                try { resolved = module.ResolveMethod(token); } catch { }

                if (resolved != null && resolved.DeclaringType == declaringType && resolved.Name == methodName)
                    count++;

                i += 4;
            }
        }

        return count;
    }

    [Test]
    public void CaptureSpawn_UsesSelectedCharacterPreset()
    {
        var spawnMenuType = FindType("SpawnMenuV2");
        var managerType = FindType("FengGameManagerMKII");
        Assert.IsNotNull(spawnMenuType, "Pipeline error: SpawnMenuV2 type not found.");
        Assert.IsNotNull(managerType, "Pipeline error: FengGameManagerMKII type not found.");

        var spawn = spawnMenuType.GetMethod("Spawn", BF);
        Assert.IsNotNull(spawn, "Pipeline error: Spawn method not found.");

        var spawnPlayerCalls = CountCallsTo(spawn, managerType, "SpawnPlayer");

        Assert.AreEqual(
            1,
            spawnPlayerCalls,
            "SpawnMenuV2.Spawn should have a single SpawnPlayer path that always receives the selected CharacterPreset.");
    }
}
#endif