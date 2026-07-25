using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;
using Fungus;

public class WriterAudioRandomRangeTests
{
    static FieldInfo F_BeepSounds
    {
        get { return typeof(WriterAudio).GetField("beepSounds", BindingFlags.Instance | BindingFlags.NonPublic); }
    }

    static FieldInfo F_PlayBeeps
    {
        get { return typeof(WriterAudio).GetField("playBeeps", BindingFlags.Instance | BindingFlags.NonPublic); }
    }

    static FieldInfo F_NextBeepTime
    {
        get { return typeof(WriterAudio).GetField("nextBeepTime", BindingFlags.Instance | BindingFlags.NonPublic); }
    }

    static FieldInfo F_TargetAudioSource
    {
        get { return typeof(WriterAudio).GetField("targetAudioSource", BindingFlags.Instance | BindingFlags.NonPublic); }
    }

    static AudioClip MakeClip(string name)
    {
        return AudioClip.Create(name, 4410, 1, 44100, false);
    }

    static void ForceReadyForNextGlyph(WriterAudio wa)
    {
        var src = (AudioSource)F_TargetAudioSource.GetValue(wa);
        if (src != null) src.Stop();
        F_NextBeepTime.SetValue(wa, -1f);
    }

    [UnityTest]
    public IEnumerator OnGlyph_CanSelectLastBeepSound()
    {
        var go = new GameObject("WriterAudio_Test");
        var wa = go.AddComponent<WriterAudio>();
        yield return null;

        var clip0 = MakeClip("clip0");
        var clip1 = MakeClip("clip1");
        F_BeepSounds.SetValue(wa, new List<AudioClip> { clip0, clip1 });
        F_PlayBeeps.SetValue(wa, true);

        bool sawLast = false;
        for (int i = 0; i < 64; i++)
        {
            ForceReadyForNextGlyph(wa);
            wa.OnGlyph();
            var src = (AudioSource)F_TargetAudioSource.GetValue(wa);
            if (src != null && src.clip == clip1) { sawLast = true; break; }
            yield return null;
        }

        Object.DestroyImmediate(go);
        Assert.That(sawLast, Is.True, "Expected WriterAudio.OnGlyph() to be able to select the last beep sound when beepSounds.Count == 2.");
    }
}
