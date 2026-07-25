#if UNITY_EDITOR
using System.Reflection;
using Assets.Scripts.Characters.Titan;
using Assets.Scripts.Characters.Titan.Configuration;
using Assets.Scripts.Gamemode;
using Assets.Scripts.Settings;
using Assets.Scripts.Settings.Titans;
using NUnit.Framework;

public class NormalTitanDeathAnimationTests
{
    static void SetStaticProperty<T>(string propertyName, T value)
    {
        var field = typeof(GameSettings).GetField(
            "<" + propertyName + ">k__BackingField",
            BindingFlags.Static | BindingFlags.NonPublic);
        Assert.IsNotNull(field, "Pipeline error: GameSettings backing field not found: " + propertyName);
        field.SetValue(null, value);
    }

    static void ConfigureTitanSettings()
    {
        SetStaticProperty("Titan", new SettingsTitan
        {
            Mindless = new MindlessTitanSettings(Difficulty.Normal)
        });
    }

    [Test]
    public void NormalTitan_UsesForwardDeathAnimation()
    {
        ConfigureTitanSettings();

        var config = new TitanConfiguration(
            healthRegeneration: 10,
            limbHealth: 100,
            viewDistance: 200f,
            type: MindlessTitanType.Normal);

        Assert.AreEqual(
            "die_front",
            config.AnimationDeath,
            "Normal Titans should use the forward death animation instead of the default backward animation.");
    }
}
#endif