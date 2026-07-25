#if UNITY_EDITOR
using System.Reflection;
using NUnit.Framework;
using UnityEngine;
using Fungus;

public class NarrativeLogCharacterLimitTests
{
    [Test]
    public void GetPrettyHistory_TruncatesOversizedNarrativeText()
    {
        var go = new GameObject("NarrativeLogCharacterLimit");
        var log = go.AddComponent<NarrativeLog>();
        InitializeHistory(log);

        try
        {
            string longLine = new string('x', 12050);
            log.AddLine(new NarrativeLogEntry { name = "Speaker", text = longLine });

            string pretty = log.GetPrettyHistory();

            Assert.That(pretty.Length, Is.LessThanOrEqualTo(10010),
                "Narrative log display text should be bounded before it can exceed Unity UI mesh limits.");
            Assert.That(pretty.StartsWith("... "), Is.True,
                "Truncated narrative log text should show that earlier content was omitted.");
        }
        finally
        {
            Object.DestroyImmediate(go);
        }
    }

    private static void InitializeHistory(NarrativeLog log)
    {
        var field = typeof(NarrativeLog).GetField(
            "history",
            BindingFlags.Instance | BindingFlags.NonPublic);

        Assert.IsNotNull(field, "Pipeline error: NarrativeLog.history field was not found.");
        field.SetValue(log, new NarrativeData());
    }
}
#endif
