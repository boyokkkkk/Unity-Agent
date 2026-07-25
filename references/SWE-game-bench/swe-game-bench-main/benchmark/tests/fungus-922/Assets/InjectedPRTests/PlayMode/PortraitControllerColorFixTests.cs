#if UNITY_EDITOR
using NUnit.Framework;
using System.Collections;
using UnityEngine;
using UnityEngine.TestTools;
using UnityEngine.UI;
using Fungus;

public class PortraitControllerColorFixTests
{
    static Sprite MakeSprite(Color c)
    {
        var tex = new Texture2D(2, 2, TextureFormat.RGBA32, false);
        tex.SetPixels(new[] { c, c, c, c });
        tex.Apply();
        return Sprite.Create(tex, new Rect(0, 0, 2, 2), new Vector2(0.5f, 0.5f));
    }

    static bool NearlyWhite(Color c)
    {
        return Mathf.Abs(c.r - 1f) < 0.02f &&
               Mathf.Abs(c.g - 1f) < 0.02f &&
               Mathf.Abs(c.b - 1f) < 0.02f;
    }

    [UnityTest]
    public IEnumerator Show_UndimsPortraitWhenColorNotWhite()
    {
        var canvasGo = new GameObject("Canvas", typeof(Canvas));
        var canvas   = canvasGo.GetComponent<Canvas>();
        canvas.renderMode = RenderMode.ScreenSpaceOverlay;

        var stageGo = new GameObject("Stage");
        stageGo.transform.SetParent(canvasGo.transform, false);
        var stage = stageGo.AddComponent<Stage>();

        yield return null;

        var posGo = new GameObject("Pos", typeof(RectTransform));
        posGo.transform.SetParent(stageGo.transform, false);
        var pos = posGo.GetComponent<RectTransform>();
        pos.anchoredPosition = Vector2.zero;

        var characterGo = new GameObject("Character");
        characterGo.transform.SetParent(stageGo.transform, false);
        var character = characterGo.AddComponent<Character>();

        var holderGo = new GameObject("Holder", typeof(RectTransform));
        holderGo.transform.SetParent(stageGo.transform, false);
        var holder = holderGo.GetComponent<RectTransform>();

        var spriteA = MakeSprite(Color.red);
        var spriteB = MakeSprite(Color.blue);

        var imgAGo = new GameObject("PortraitA", typeof(RectTransform), typeof(CanvasRenderer), typeof(Image));
        imgAGo.transform.SetParent(holderGo.transform, false);
        var imgA = imgAGo.GetComponent<Image>();
        imgA.sprite = spriteA;
        imgA.color  = Color.white;
        imgAGo.SetActive(true);

        var imgBGo = new GameObject("PortraitB", typeof(RectTransform), typeof(CanvasRenderer), typeof(Image));
        imgBGo.transform.SetParent(holderGo.transform, false);
        var imgB = imgBGo.GetComponent<Image>();
        imgB.sprite = spriteB;
        imgB.color  = new Color(0.4f, 0.4f, 0.4f, 1f);
        imgBGo.SetActive(false);

        character.State.holder        = holder;
        character.State.position      = pos;
        character.State.allPortraits.Clear();
        character.State.allPortraits.Add(imgA);
        character.State.allPortraits.Add(imgB);
        character.State.portraitImage = imgA;
        character.State.onScreen      = true;

        var options = new PortraitOptions(false);
        options.character        = character;
        options.display          = DisplayType.Show;
        options.portrait         = spriteB;
        options.fromPosition     = pos;
        options.toPosition       = pos;
        options.move             = false;
        options.shiftIntoPlace   = false;
        options.waitUntilFinished = false;
        options.fadeDuration     = 0.05f;
        options.moveDuration     = 0.01f;

        stage.Show(options);

        float start = Time.realtimeSinceStartup;
        while (Time.realtimeSinceStartup - start < 1.0f)
        {
            if (character.State.portraitImage != null && NearlyWhite(character.State.portraitImage.color))
                break;
            yield return null;
        }

        Assert.That(character.State.portraitImage != null, Is.True);
        Assert.That(NearlyWhite(character.State.portraitImage.color), Is.True);
    }
}
#endif
