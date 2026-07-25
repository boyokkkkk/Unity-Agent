#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Reflection;
using System.Runtime.Serialization;
using NUnit.Framework;
using UnityEngine;

public class RoundSoloSuicideTests
{
    static readonly BindingFlags InstanceFlags =
        BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

    // Round.OnDeath subscribes via PlayerManager.onDeath, but the bug we are testing lives entirely
    // inside the suicide branch of OnDeath itself. We bypass Round's constructor (which would
    // require MatchController.Singleton, MusicTrackManager.Singleton, and live event wiring) and
    // initialize only the private fields OnDeath actually reads. We then invoke OnDeath via
    // reflection. This keeps the test focused on the one-line bug fix.

    [Test]
    public void OnDeath_SoloSuicide_DoesNotThrowFromEmptyLivingPlayersList()
    {
        var playerGo = new GameObject("solo-player");
        try
        {
            playerGo.AddComponent<BoxCollider>();
            var player = playerGo.AddComponent<PlayerManager>();

            var round = (Round)FormatterServices.GetUninitializedObject(typeof(Round));

            var players = new List<PlayerManager> { player };
            var livingPlayers = new List<PlayerManager> { player };
            var killsBacking = new Dictionary<PlayerManager, List<PlayerManager>>
            {
                { player, new List<PlayerManager>() }
            };
            var kills = new ReadOnlyDictionary<PlayerManager, List<PlayerManager>>(killsBacking);

            var roundType = typeof(Round);
            roundType.GetField("players", InstanceFlags).SetValue(round, players);
            roundType.GetField("livingPlayers", InstanceFlags).SetValue(round, livingPlayers);
            roundType.GetField("kills", InstanceFlags).SetValue(round, kills);

            var onDeath = roundType.GetMethod("OnDeath", InstanceFlags);
            Assert.IsNotNull(onDeath, "Pipeline error: Round.OnDeath should exist as a private instance method.");

            // Discriminator: the buggy line is `CheckWinCondition(livingPlayers.First())`.
            // On base, livingPlayers is empty after Remove(victim), so .First() throws
            // InvalidOperationException("Sequence contains no elements").
            // On patched, .FirstOrDefault() returns null and execution falls through to
            // CheckWinCondition(null), which then calls MatchController.Singleton.EndActiveRound().
            // The Singleton is null in the test environment, so a NullReferenceException fires.
            // That NRE is environmental (not the bug under test); it proves the fix reached the
            // post-bug code path. We discriminate strictly on InvalidOperationException.
            InvalidOperationException buggyThrow = null;
            try
            {
                onDeath.Invoke(round, new object[] { player, player });
            }
            catch (TargetInvocationException tie) when (tie.InnerException is InvalidOperationException ioe)
            {
                buggyThrow = ioe;
            }
            catch (TargetInvocationException)
            {
                // Other inner exceptions (e.g. NullReferenceException from MatchController.Singleton being
                // null after the suicide branch already returned a value) happen AFTER the buggy line and
                // mean the fix succeeded. Suppress them.
            }

            Assert.IsNull(
                buggyThrow,
                "Solo suicide should not throw InvalidOperationException from livingPlayers.First() on the empty list. " +
                "Replace .First() with .FirstOrDefault() so CheckWinCondition receives null when no player remains.");
        }
        finally
        {
            UnityEngine.Object.DestroyImmediate(playerGo);
        }
    }
}
#endif