#if UNITY_EDITOR
using System.IO;
using NUnit.Framework;
using UnityEngine;

public class ChatRegisterTagEscapingTests
{
    static string ReadChatRegisterSource()
    {
        var candidates = new[]
        {
            Path.Combine(Application.dataPath, "Engine/Chat/ChatRegister.cs"),
            Path.Combine(Application.dataPath, "Scripts/SS3D/Engine/Chat/ChatRegister.cs")
        };

        foreach (var candidate in candidates)
            if (File.Exists(candidate))
                return File.ReadAllText(candidate);

        Assert.Fail("Could not find ChatRegister.cs in known project paths.");
        return null;
    }

    static string Compact(string text)
    {
        return text.Replace(" ", "").Replace("\t", "").Replace("\r", "").Replace("\n", "");
    }

    [Test]
    public void CmdSendMessage_EscapesAngleBracketsInUnrestrictedChannels()
    {
        string source = ReadChatRegisterSource();
        string compact = Compact(source);

        Assert.IsTrue(source.Contains("<nobr><</nobr>"),
            "Base commit bug: ChatRegister did not contain the literal '<' escaping sequence.");
        Assert.IsTrue(compact.Contains("chatMessage.Text=chatMessage.Text.Replace(\"<\",\"<nobr><</nobr>\")"),
            "CmdSendMessage should escape '<' to '<nobr><</nobr>' before broadcasting unrestricted chat.");

        int restrictedCheck = compact.IndexOf("restrictedChannels.Contains(chatMessage.Channel.Name)");
        int escape = compact.IndexOf("<nobr><</nobr>");
        int senderAssignment = compact.IndexOf("chatMessage.Sender=");

        Assert.GreaterOrEqual(restrictedCheck, 0, "CmdSendMessage should still check restricted channels.");
        Assert.Greater(escape, restrictedCheck, "Escaping should happen only after restricted channels return early.");
        Assert.Greater(senderAssignment, escape, "Escaping should happen before the message is prepared for broadcast.");
    }
}
#endif