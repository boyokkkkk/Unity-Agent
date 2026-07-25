#if UNITY_EDITOR
using Assets.Scripts.Gamemode;
using Assets.Scripts.Settings.Gamemodes;
using NUnit.Framework;

public class GamemodeHorseDefaultsTests
{
    [Test]
    public void NewGamemodeSettings_DisablesHorsesByDefault()
    {
        var settings = new GamemodeSettings(Difficulty.Normal);

        Assert.IsNotNull(settings.Horse, "Pipeline error: Horse settings should be created.");
        Assert.IsTrue(settings.Horse.Enabled.HasValue, "Horse.Enabled should be explicitly initialized.");
        Assert.IsFalse(
            settings.Horse.Enabled.Value,
            "New gamemode settings should disable horses by default so they do not carry across maps.");
    }
}
#endif