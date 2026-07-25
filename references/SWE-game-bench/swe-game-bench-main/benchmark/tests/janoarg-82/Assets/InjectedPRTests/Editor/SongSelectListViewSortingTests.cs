#if UNITY_EDITOR
using System;
using System.Linq;
using System.Reflection;
using JANOARG.Client.Behaviors.SongSelect;
using JANOARG.Client.Behaviors.SongSelect.List;
using JANOARG.Client.Behaviors.SongSelect.List.ListItems;
using JANOARG.Client.Behaviors.SongSelect.Map;
using JANOARG.Client.Behaviors.SongSelect.Map.MapItems;
using JANOARG.Client.Data.Playlist;
using JANOARG.Shared.Data.ChartInfo;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.UI;

public class SongSelectListViewSortingTests
{
    static readonly BindingFlags InstanceFlags =
        BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;

    static void SetRevealed(MapItem item, bool value)
    {
        var backingField = typeof(MapItem).GetField("<isRevealed>k__BackingField", InstanceFlags);
        backingField.SetValue(item, value);
    }

    static SongSelectListView MakeListView(GameObject root, SongSortCriteria criteria)
    {
        var screen = root.AddComponent<SongSelectScreen>();
        SongSelectScreen.sMain = screen;
        screen.TargetSongCoverHolder = new GameObject("cover-holder", typeof(RectTransform)).GetComponent<RectTransform>();
        screen.TargetSongCoverHolder.SetParent(root.transform);

        var filter = root.AddComponent<SongSelectFilterPanel>();
        filter.CurrentSortCriteria = criteria;
        filter.SortReversed = false;

        var view = root.AddComponent<SongSelectListView>();
        view.FilterPanel = filter;
        view.ItemHolder = new GameObject("item-holder", typeof(RectTransform)).GetComponent<RectTransform>();
        view.ItemHolder.SetParent(root.transform);
        view.ItemCursor = new GameObject("item-cursor", typeof(Image)).GetComponent<Image>();
        view.ItemCursor.transform.SetParent(root.transform);
        view.ScrollOffset = -100000f;
        view.SongItemSize = 0f;
        view.SongHeaderSize = 0f;
        return view;
    }

    static void AddSong(GameObject root, string id, string title, string artist, float chartConstant)
    {
        var screen = SongSelectScreen.sMain;
        screen.PlaylistSongByID[id] = new PlaylistSong
        {
            ID = id,
            RevealConditions = Array.Empty<GameConditional>(),
            UnlockConditions = Array.Empty<GameConditional>(),
        };
        screen.PlayableSongByID[id] = new PlayableSong
        {
            SongName = title,
            SongArtist = artist,
            Charts =
            {
                new ExternalChartMeta
                {
                    Target = id + ".jac",
                    DifficultyIndex = 0,
                    ChartConstant = chartConstant,
                    DifficultyName = "Normal",
                    DifficultyLevel = chartConstant.ToString("0.0"),
                }
            }
        };

        var mapItem = root.AddComponent<SongMapItem>();
        mapItem.TargetID = id;
        SetRevealed(mapItem, true);
        MapManager.sSongMapItemsByID[id] = mapItem;
    }

    static string[] SongOrder(SongSelectListView view)
    {
        return view.ItemList
            .OfType<SongSelectListSong>()
            .Select(item => item.SongID)
            .ToArray();
    }

    [SetUp]
    public void SetUp()
    {
        MapManager.sSongMapItemsByID.Clear();
        SongSelectScreen.sMain = null;
    }

    [TearDown]
    public void TearDown()
    {
        MapManager.sSongMapItemsByID.Clear();
        SongSelectScreen.sMain = null;
    }

    // UpdateSort() populates view.ItemList (what these tests assert on) and then calls
    // UpdateListItems() to render UI rows. Rendering needs SongItemSample/SongHeaderSample
    // prefab references which the EditMode test environment cannot provide without dragging
    // in 8+ unrelated UI components per row. We narrowly swallow the rendering-only exception
    // so the assertion still runs against the (already-populated) ItemList.
    static void RunSortIgnoringRender(SongSelectListView view)
    {
        try { view.UpdateSort(); }
        catch (System.ArgumentException e) when (e.Message.Contains("Object you want to instantiate is null")) { }
    }

    [Test]
    public void TitleSortUsesSongNameInsteadOfArtist()
    {
        var root = new GameObject("title-sort-root");
        try
        {
            var view = MakeListView(root, SongSortCriteria.Title);
            AddSong(root, "artist-first", "Zeta Title", "Alpha Artist", 9.2f);
            AddSong(root, "title-first", "Alpha Title", "Zeta Artist", 9.2f);

            RunSortIgnoringRender(view);

            CollectionAssert.AreEqual(
                new[] { "title-first", "artist-first" },
                SongOrder(view),
                "Title sorting should order by PlayableSong.SongName, not PlayableSong.SongArtist."
            );
        }
        finally
        {
            UnityEngine.Object.DestroyImmediate(root);
        }
    }

}
#endif