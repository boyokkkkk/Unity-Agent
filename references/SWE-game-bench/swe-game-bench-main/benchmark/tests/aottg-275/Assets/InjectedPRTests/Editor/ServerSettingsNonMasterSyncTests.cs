#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.Reflection.Emit;
using System.Reflection;
using NUnit.Framework;

public class ServerSettingsNonMasterSyncTests
{
    static readonly BindingFlags BF =
        BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Static;

    static readonly Dictionary<short, OpCode> OpCodesByValue = BuildOpcodeMap();

    static Dictionary<short, OpCode> BuildOpcodeMap()
    {
        var map = new Dictionary<short, OpCode>();
        foreach (var field in typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static))
        {
            if (field.GetValue(null) is OpCode op)
                map[op.Value] = op;
        }
        return map;
    }

    static Type FindType(string fullName, string shortName)
    {
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            Type[] types;
            try { types = asm.GetTypes(); }
            catch (ReflectionTypeLoadException e) { types = e.Types; }
            catch { continue; }

            if (types == null) continue;
            foreach (var t in types)
            {
                if (t == null) continue;
                if (t.FullName == fullName || t.Name == shortName)
                    return t;
            }
        }
        return null;
    }

    static int OperandSize(OpCode op, byte[] il, int offset)
    {
        switch (op.OperandType)
        {
            case OperandType.InlineNone:
                return 0;
            case OperandType.ShortInlineBrTarget:
            case OperandType.ShortInlineI:
            case OperandType.ShortInlineVar:
                return 1;
            case OperandType.InlineVar:
                return 2;
            case OperandType.InlineI:
            case OperandType.InlineBrTarget:
            case OperandType.InlineField:
            case OperandType.InlineMethod:
            case OperandType.InlineSig:
            case OperandType.InlineString:
            case OperandType.InlineTok:
            case OperandType.InlineType:
            case OperandType.ShortInlineR:
                return 4;
            case OperandType.InlineI8:
            case OperandType.InlineR:
                return 8;
            case OperandType.InlineSwitch:
                int count = BitConverter.ToInt32(il, offset);
                return 4 + (4 * count);
            default:
                throw new NotSupportedException("Unsupported operand type: " + op.OperandType);
        }
    }

    static bool HasEarlyReturnBeforeStaticSettingWrites(MethodInfo method)
    {
        var body = method.GetMethodBody();
        Assert.IsNotNull(body, "Pipeline error: Sync method has no method body.");

        var il = body.GetILAsByteArray();
        var module = method.Module;
        bool sawMasterClientCheck = false;

        for (int i = 0; i < il.Length;)
        {
            int instructionStart = i;
            short value = il[i++];
            if (value == 0xFE)
                value = (short)(0xFE00 | il[i++]);

            var op = OpCodesByValue[value];
            int operandOffset = i;
            int size = OperandSize(op, il, operandOffset);

            if ((op == OpCodes.Call || op == OpCodes.Callvirt) && size == 4)
            {
                int token = BitConverter.ToInt32(il, operandOffset);
                MethodBase resolved = null;
                try { resolved = module.ResolveMethod(token); } catch { }
                if (resolved != null && resolved.DeclaringType != null
                    && resolved.DeclaringType.Name == "PhotonNetwork"
                    && resolved.Name == "get_isMasterClient")
                {
                    sawMasterClientCheck = true;
                }
            }

            if (op == OpCodes.Stsfld && size == 4)
            {
                int token = BitConverter.ToInt32(il, operandOffset);
                FieldInfo field = null;
                try { field = module.ResolveField(token); } catch { }
                if (field != null && field.DeclaringType != null
                    && field.DeclaringType.Name == "FengGameManagerMKII"
                    && (field.Name.Contains("NewRoundGamemode") || field.Name.Contains("NewRoundLevel")))
                {
                    return false;
                }
            }

            if (sawMasterClientCheck && op == OpCodes.Ret)
                return true;

            i += size;
        }

        return false;
    }

    [Test]
    public void Sync_ReturnsEarlyForNonMasterBeforeChangingNextRoundState()
    {
        var pageType = FindType("Assets.Scripts.UI.InGame.ServerSettingsPage", "ServerSettingsPage");
        Assert.IsNotNull(pageType, "Pipeline error: ServerSettingsPage type not found.");

        var sync = pageType.GetMethod("Sync", BF);
        Assert.IsNotNull(sync, "Pipeline error: Sync method not found.");

        Assert.IsTrue(
            HasEarlyReturnBeforeStaticSettingWrites(sync),
            "Sync should check PhotonNetwork.isMasterClient and return before writing NewRoundGamemode/NewRoundLevel.");
    }
}
#endif