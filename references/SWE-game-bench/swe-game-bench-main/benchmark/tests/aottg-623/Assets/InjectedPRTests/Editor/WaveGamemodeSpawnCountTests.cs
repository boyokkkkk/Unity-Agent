#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.Reflection;
using System.Reflection.Emit;
using Assets.Scripts.Gamemode;
using Assets.Scripts.Settings.Gamemodes;
using NUnit.Framework;
using UnityEngine;

public class WaveGamemodeSpawnCountTests
{
    static readonly Dictionary<short, OpCode> OpCodesByValue = BuildOpcodeMap();

    static Dictionary<short, OpCode> BuildOpcodeMap()
    {
        var result = new Dictionary<short, OpCode>();
        foreach (var field in typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static))
        {
            if (field.FieldType == typeof(OpCode))
            {
                var opcode = (OpCode)field.GetValue(null);
                result[opcode.Value] = opcode;
            }
        }
        return result;
    }

    static IEnumerable<Tuple<OpCode, MethodBase>> ReadInstructions(MethodInfo method)
    {
        var body = method.GetMethodBody();
        Assert.IsNotNull(body, "Pipeline error: method has no body.");

        byte[] il = body.GetILAsByteArray();
        int offset = 0;
        while (offset < il.Length)
        {
            short value = il[offset++];
            if (value == 0xFE)
                value = (short)(0xFE00 | il[offset++]);

            OpCode opcode;
            Assert.IsTrue(OpCodesByValue.TryGetValue(value, out opcode), "Unknown IL opcode.");

            MethodBase calledMethod = null;
            int operandSize;
            switch (opcode.OperandType)
            {
                case OperandType.InlineMethod:
                    int token = BitConverter.ToInt32(il, offset);
                    try { calledMethod = method.Module.ResolveMethod(token); } catch { }
                    operandSize = 4;
                    break;
                case OperandType.InlineSwitch:
                    int targets = BitConverter.ToInt32(il, offset);
                    operandSize = 4 + targets * 4;
                    break;
                case OperandType.InlineI8:
                case OperandType.InlineR:
                    operandSize = 8;
                    break;
                case OperandType.InlineBrTarget:
                case OperandType.InlineField:
                case OperandType.InlineI:
                case OperandType.InlineSig:
                case OperandType.InlineString:
                case OperandType.InlineTok:
                case OperandType.InlineType:
                case OperandType.ShortInlineR:
                    operandSize = 4;
                    break;
                case OperandType.InlineVar:
                    operandSize = 2;
                    break;
                case OperandType.ShortInlineBrTarget:
                case OperandType.ShortInlineI:
                case OperandType.ShortInlineVar:
                    operandSize = 1;
                    break;
                default:
                    operandSize = 0;
                    break;
            }

            yield return Tuple.Create(opcode, calledMethod);
            offset += operandSize;
        }
    }

    [Test]
    public void ForestWaveSettings_StartAtThreeAndIncreaseByOne()
    {
        var settings = new WaveGamemodeSettings(Difficulty.Normal);

        Assert.AreEqual(3, settings.Titan.Start.Value, "Forest wave mode should start with 3 titans.");
        Assert.AreEqual(1, settings.WaveIncrement.Value, "Forest wave mode should increase by 1 titan per normal wave.");
        Assert.AreEqual(5, settings.BossWave.Value, "Every fifth wave should remain a boss wave.");
    }

    [Test]
    public void NextWave_UsesCompletedWaveOffsetForNormalCount()
    {
        var nextWave = typeof(WaveGamemode).GetMethod(
            "NextWave",
            BindingFlags.Instance | BindingFlags.NonPublic);
        Assert.IsNotNull(nextWave, "Pipeline error: existing NextWave method not found.");

        bool subtractsWaveOffset = false;
        foreach (var instruction in ReadInstructions(nextWave))
            subtractsWaveOffset |= instruction.Item1 == OpCodes.Sub;

        Assert.IsTrue(
            subtractsWaveOffset,
            "Normal-wave count does not apply the required Wave - 1 offset.");
    }

    [Test]
    public void NextWave_UsesCoroutineSpawnPathsForNormalAndBossWaves()
    {
        var nextWave = typeof(WaveGamemode).GetMethod(
            "NextWave",
            BindingFlags.Instance | BindingFlags.NonPublic);
        Assert.IsNotNull(nextWave, "Pipeline error: existing NextWave method not found.");

        int coroutineSpawnPaths = 0;
        foreach (var instruction in ReadInstructions(nextWave))
        {
            MethodBase called = instruction.Item2;
            if (called != null &&
                called.Name == "StartCoroutine" &&
                typeof(MonoBehaviour).IsAssignableFrom(called.DeclaringType))
            {
                coroutineSpawnPaths++;
            }
        }

        Assert.GreaterOrEqual(
            coroutineSpawnPaths,
            2,
            "NextWave must route both normal and boss waves through coroutine spawn paths.");
    }
}
#endif
