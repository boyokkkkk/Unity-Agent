#if UNITY_EDITOR
using System;
using System.Reflection;
using NUnit.Framework;

public class PlayerMovementToggleModeTests
{
    static readonly BindingFlags PublicInstance = BindingFlags.Instance | BindingFlags.Public;

    static Type FindRuntimeType(string fullName)
    {
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            Type type = asm.GetType(fullName, false);
            if (type != null)
                return type;
        }
        return null;
    }

    static Type GetRuntimeType(string typeName)
    {
        return FindRuntimeType("Hertzole.GoldPlayer.Core." + typeName);
    }

    [Test]
    public void ToggleModeEnums_AreAvailableWithExpectedValues()
    {
        Type runToggleMode = GetRuntimeType("RunToggleMode");
        Type crouchToggleMode = GetRuntimeType("CrouchToggleMode");

        Assert.IsNotNull(runToggleMode, "RunToggleMode enum must exist for configurable run toggling.");
        Assert.IsNotNull(crouchToggleMode, "CrouchToggleMode enum must exist for configurable crouch toggling.");

        Assert.IsTrue(runToggleMode.IsEnum, "RunToggleMode should be an enum.");
        Assert.IsTrue(crouchToggleMode.IsEnum, "CrouchToggleMode should be an enum.");

        Assert.AreEqual(0, Convert.ToInt32(Enum.Parse(runToggleMode, "Off")));
        Assert.AreEqual(1, Convert.ToInt32(Enum.Parse(runToggleMode, "Permanent")));
        Assert.AreEqual(2, Convert.ToInt32(Enum.Parse(runToggleMode, "UntilNoInput")));

        Assert.AreEqual(0, Convert.ToInt32(Enum.Parse(crouchToggleMode, "Off")));
        Assert.AreEqual(1, Convert.ToInt32(Enum.Parse(crouchToggleMode, "Permanent")));
    }

    [Test]
    public void PlayerMovement_ExposesWritableToggleModeProperties()
    {
        Type movementType = GetRuntimeType("PlayerMovement");
        Type runToggleMode = GetRuntimeType("RunToggleMode");
        Type crouchToggleMode = GetRuntimeType("CrouchToggleMode");

        Assert.IsNotNull(movementType, "PlayerMovement type must exist.");
        Assert.IsNotNull(runToggleMode, "RunToggleMode enum must exist.");
        Assert.IsNotNull(crouchToggleMode, "CrouchToggleMode enum must exist.");

        PropertyInfo runProperty = movementType.GetProperty("RunToggleMode", PublicInstance);
        PropertyInfo crouchProperty = movementType.GetProperty("CrouchToggleMode", PublicInstance);

        Assert.IsNotNull(runProperty, "PlayerMovement must expose RunToggleMode.");
        Assert.IsNotNull(crouchProperty, "PlayerMovement must expose CrouchToggleMode.");
        Assert.AreEqual(runToggleMode, runProperty.PropertyType);
        Assert.AreEqual(crouchToggleMode, crouchProperty.PropertyType);
        Assert.IsTrue(runProperty.CanRead && runProperty.CanWrite, "RunToggleMode must be readable and writable.");
        Assert.IsTrue(crouchProperty.CanRead && crouchProperty.CanWrite, "CrouchToggleMode must be readable and writable.");

        object movement = Activator.CreateInstance(movementType);
        object untilNoInput = Enum.Parse(runToggleMode, "UntilNoInput");
        object permanentCrouch = Enum.Parse(crouchToggleMode, "Permanent");

        runProperty.SetValue(movement, untilNoInput, null);
        crouchProperty.SetValue(movement, permanentCrouch, null);

        Assert.AreEqual(untilNoInput, runProperty.GetValue(movement, null));
        Assert.AreEqual(permanentCrouch, crouchProperty.GetValue(movement, null));
    }
}
#endif
