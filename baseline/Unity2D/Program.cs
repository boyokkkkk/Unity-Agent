using SkillGameAgent.Unity2D;

if (args.Contains("--test"))
{
    var task = args.LastOrDefault() ?? "";
    switch (task)
    {
        case "A1-player-dash": Assert(PlayerMovement.DashDistance == 4, "player dash"); break;
        case "B1-damage-invincibility": Assert(HealthState.InvincibilityFrames == 30, "damage invincibility"); break;
        case "C1-pickup-counter": Assert(PickupCounter.PickupValue == 1, "pickup counter"); break;
        default: throw new InvalidOperationException($"Unknown task: {task}");
    }
    Console.WriteLine("WEEK1_TESTS_PASSED");
}

static void Assert(bool condition, string name)
{
    if (!condition) throw new InvalidOperationException($"FAILED: {name}");
}
