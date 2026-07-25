#if UNITY_EDITOR
using System.Reflection;
using JANOARG.Client.Behaviors.Common;
using JANOARG.Client.Behaviors.Player;
using JANOARG.Shared.Data.ChartInfo;
using NUnit.Framework;
using TMPro;
using UnityEngine;
using UnityEngine.TestTools;
using UnityEngine.UI;

public class PlayerScreenNegativeVisualTimeTests
{
    static readonly BindingFlags InstanceFlags =
        BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

    static T Add<T>(GameObject root, string name) where T : Component
    {
        var go = new GameObject(name);
        go.transform.SetParent(root.transform);
        return go.AddComponent<T>();
    }

    static TMP_Text AddText(GameObject root, string name)
    {
        return Add<TextMeshProUGUI>(root, name);
    }

    static LanePlayer CreateLane(GameObject root)
    {
        var laneGo = new GameObject("negative-time-lane");
        laneGo.transform.SetParent(root.transform);

        var lane = laneGo.AddComponent<LanePlayer>();

        lane.Holder = new GameObject("holder").transform;
        lane.Holder.SetParent(laneGo.transform);

        lane.MeshFilter = Add<MeshFilter>(laneGo, "mesh-filter");
        lane.MeshRenderer = Add<MeshRenderer>(laneGo, "mesh-renderer");
        lane.JudgeLine = Add<MeshRenderer>(laneGo, "judge-line");
        lane.JudgePointLeft = Add<MeshRenderer>(laneGo, "judge-left");
        lane.JudgePointRight = Add<MeshRenderer>(laneGo, "judge-right");

        lane.Original = new Lane
        {
            StyleIndex = -1
        };

        lane.Current = new Lane
        {
            StyleIndex = -1
        };

        lane.Current.LaneSteps.Add(new LaneStep
        {
            Offset = new BeatPosition(-1),
            Speed = 1,
            StartPos = new Vector2(-1, 0),
            EndPos = new Vector2(1, 0),
        });

        lane.Current.LaneSteps.Add(new LaneStep
        {
            Offset = new BeatPosition(1),
            Speed = 1,
            StartPos = new Vector2(-1, 1),
            EndPos = new Vector2(1, 1),
        });

        lane.TimeStamps.Add(-1f);
        lane.TimeStamps.Add(1f);

        return lane;
    }

    [Test]
    public void Update_UsesNegativeVisualTime_WhenCurrentTimePlusVisualOffsetIsNegative()
    {
        var root = new GameObject("negative-visual-time-root");

        try
        {
            var common = root.AddComponent<CommonSys>();
            common.MainCamera = Add<Camera>(root, "main-camera");
            CommonSys.main = common;

            var screen = root.AddComponent<PlayerScreen>();
            PlayerScreen.main = screen;

            screen.Speed = 100f;

            screen.Music = Add<AudioSource>(root, "music");
            screen.Music.clip = AudioClip.Create("silent", 44100, 1, 44100, false);

            screen.SongProgress = Add<Slider>(root, "song-progress");
            screen.SongProgressBody = Add<Image>(root, "progress-body");
            screen.SongProgressTip = Add<Image>(root, "progress-tip");
            screen.SongProgressGlow = Add<Image>(root, "progress-glow");

            screen.SongNameLabel = AddText(root, "song-name");
            screen.SongArtistLabel = AddText(root, "song-artist");
            screen.DifficultyNameLabel = AddText(root, "difficulty-name");
            screen.DifficultyLabel = AddText(root, "difficulty");
            screen.JudgmentLabel = AddText(root, "judgment");
            screen.ComboLabel = AddText(root, "combo");
            screen.PauseLabel = AddText(root, "pause");

            screen.HitObjectHistory = new System.Collections.Generic.List<HitObjectHistoryItem>();
            screen.Settings = new PlayerSettings { VisualOffset = 0f };

            const float negativeVisualTime = -2.25f;
            screen.CurrentTime = negativeVisualTime;
            screen.IsPlaying = true;
            screen.HitsRemaining = 1;

            var lane = CreateLane(root);
            screen.Lanes.Add(lane);

            var input = root.AddComponent<PlayerInputManager>();
            input.Player = screen;
            input.Autoplay = true;
            PlayerInputManager.Instance = input;

            PlayerScreen.TargetSong = new PlayableSong
            {
                Timing = new Metronome(60)
            };

            PlayerScreen.CurrentChart = new Chart();
            PlayerScreen.CurrentChart.Palette.InterfaceColor = screen.SongNameLabel.color;
            PlayerScreen.CurrentChart.Palette.BackgroundColor = common.MainCamera.backgroundColor;

            FieldInfo lastDspTime = typeof(PlayerScreen).GetField("lastDSPTime", InstanceFlags);
            Assert.IsNotNull(lastDspTime, "Could not initialize PlayerScreen.lastDSPTime.");
            lastDspTime.SetValue(screen, AudioSettings.dspTime);

            // Act: the PR changed the visual-time calculation used by the visual/lane update.
            LogAssert.Expect(
                LogType.Error,
                "Instantiating mesh due to calling MeshFilter.mesh during edit mode. This will leak meshes. Please use MeshFilter.sharedMesh instead."
            );
            screen.Update();

            float visualTime = screen.CurrentTime + screen.Settings.VisualOffset;
            Assert.That(
                visualTime,
                Is.LessThan(0f),
                "The fixture must still be exercising the negative-time path after Update advances the song clock."
            );

            // For a visual time before the first timestamp, LanePlayer calculates:
            //
            // CurrentPosition = visualTime * laneSpeed * PlayerScreen.Speed
            //
            // Old buggy code clamps visualTime to 0, so this would become positive instead.
            float expectedCurrentPosition = visualTime * 1f * screen.Speed;

            Assert.That(
                lane.CurrentPosition,
                Is.EqualTo(expectedCurrentPosition).Within(0.001f),
                "Lane update should receive the real negative visual time, not a value clamped to zero."
            );

            Assert.That(
                lane.CurrentPosition,
                Is.LessThan(0f),
                "This specifically guards against the old ChartUpdateTime clamp."
            );

            Assert.That(
                lane.Holder.localPosition.z,
                Is.EqualTo(-expectedCurrentPosition).Within(0.001f),
                "The lane holder position should reflect the negative CurrentPosition."
            );
        }
        finally
        {
            Object.DestroyImmediate(root);

            PlayerScreen.main = null;
            PlayerScreen.TargetSong = null;
            PlayerScreen.CurrentChart = null;
            PlayerInputManager.Instance = null;
            CommonSys.main = null;
        }
    }
}
#endif
