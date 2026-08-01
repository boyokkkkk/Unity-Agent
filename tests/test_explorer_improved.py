"""Test improved Explorer functionality.

Tests:
1. Real tool schema loading
2. Evidence extraction from different tool types
3. LLM-based summary generation
"""

from pathlib import Path
from unittest.mock import Mock

from game_agent_try.agents import ExplorerAgent, ExplorationTask
from game_agent_try.aci.schemas import STRUCTURED_QUERY_TOOLS


def test_tool_schema_loading():
    """Test that Explorer loads real tool schemas."""
    print("Testing tool schema loading...")

    mock_model = Mock()
    mock_context = Mock()
    mock_context.project_store = Mock()

    project_root = Path(__file__).parent.parent / "test_project"

    explorer = ExplorerAgent(
        model=mock_model,
        context=mock_context,
        project_root=project_root,
    )

    # Get tool schemas
    tools = explorer._get_tool_schemas()

    # Should have multiple tools
    assert len(tools) > 0
    print(f"  ✓ Loaded {len(tools)} tool schemas")

    # Check structure
    for tool in tools:
        assert "type" in tool
        assert "function" in tool
        assert "name" in tool["function"]
        assert "description" in tool["function"]
        assert "parameters" in tool["function"]

    print(f"  ✓ Tool schemas have correct structure")

    # List tool names
    tool_names = [tool["function"]["name"] for tool in tools]
    print(f"  ✓ Tools available: {', '.join(tool_names[:5])}...")

    # Should not include candidate_read (that's for Coordinator)
    assert "candidate_read" not in tool_names
    print("  ✓ candidate_read correctly excluded")

    # Should include key search tools
    assert "unity_asset_search" in tool_names
    assert "code_symbol_search" in tool_names
    print("  ✓ Key search tools included")

    print("✓ Tool schema loading working correctly\n")


def test_evidence_extraction_search():
    """Test evidence extraction from search results."""
    print("Testing evidence extraction (search)...")

    mock_model = Mock()
    mock_context = Mock()
    mock_context.project_store = Mock()

    project_root = Path(__file__).parent.parent / "test_project"

    explorer = ExplorerAgent(
        model=mock_model,
        context=mock_context,
        project_root=project_root,
    )

    # Simulate search result
    search_result = {
        "status": "success",
        "nodes": [
            {
                "id": "node1",
                "kind": "CLASS",
                "path": "Assets/Scripts/GameStateManager.cs",
                "name": "GameStateManager",
            },
            {
                "id": "node2",
                "kind": "METHOD",
                "path": "Assets/Scripts/GameStateManager.cs",
                "name": "TransitionToWin",
            },
        ],
        "query": "GameStateManager",
    }

    explorer._extract_evidence("unity_asset_search", search_result)

    # Should create evidence
    assert len(explorer.evidence_items) == 1
    evidence = explorer.evidence_items[0]
    assert evidence.source == "unity_asset_search"
    assert "GameStateManager" in evidence.content or "CLASS" in evidence.content
    print("  ✓ Evidence created from search results")

    # Should create candidates
    assert len(explorer.candidate_nodes) == 2
    candidate1 = explorer.candidate_nodes[0]
    assert candidate1.node_id == "node1"
    assert candidate1.role == "CLASS"
    assert candidate1.path == "Assets/Scripts/GameStateManager.cs"
    print("  ✓ Candidate nodes extracted")

    print("✓ Search evidence extraction working\n")


def test_evidence_extraction_read():
    """Test evidence extraction from read results."""
    print("Testing evidence extraction (read)...")

    mock_model = Mock()
    mock_context = Mock()
    mock_context.project_store = Mock()

    project_root = Path(__file__).parent.parent / "test_project"

    explorer = ExplorerAgent(
        model=mock_model,
        context=mock_context,
        project_root=project_root,
    )

    # Simulate file read result
    read_result = {
        "status": "success",
        "path": "Assets/Scripts/GameStateManager.cs",
        "content": "public class GameStateManager {\n    public void TransitionToWin() {\n        // TODO\n    }\n}",
        "sha256": "abc123",
    }

    explorer._extract_evidence("code_file_read", read_result)

    # Should create evidence with truncated content
    assert len(explorer.evidence_items) == 1
    evidence = explorer.evidence_items[0]
    assert evidence.source == "code_file_read"
    assert "GameStateManager.cs" in evidence.content
    assert evidence.metadata["path"] == "Assets/Scripts/GameStateManager.cs"
    assert evidence.metadata["sha256"] == "abc123"
    print("  ✓ Evidence created from file read")

    print("✓ Read evidence extraction working\n")


def test_evidence_extraction_references():
    """Test evidence extraction from reference search."""
    print("Testing evidence extraction (references)...")

    mock_model = Mock()
    mock_context = Mock()
    mock_context.project_store = Mock()

    project_root = Path(__file__).parent.parent / "test_project"

    explorer = ExplorerAgent(
        model=mock_model,
        context=mock_context,
        project_root=project_root,
    )

    # Simulate reference search result
    ref_result = {
        "status": "success",
        "rows": [
            {
                "source": {"name": "PlayerController", "path": "Assets/Scripts/PlayerController.cs"},
                "target": {"name": "GameStateManager", "path": "Assets/Scripts/GameStateManager.cs"},
                "edge_kind": "CALLS",
            },
            {
                "source": {"name": "UIManager", "path": "Assets/Scripts/UIManager.cs"},
                "target": {"name": "GameStateManager", "path": "Assets/Scripts/GameStateManager.cs"},
                "edge_kind": "SERIALIZED_REF",
            },
        ],
    }

    explorer._extract_evidence("code_find_references", ref_result)

    # Should create evidence with relationships
    assert len(explorer.evidence_items) == 1
    evidence = explorer.evidence_items[0]
    assert evidence.source == "code_find_references"
    assert "CALLS" in evidence.content or "PlayerController" in evidence.content
    assert evidence.metadata["reference_count"] == 2
    print("  ✓ Evidence created from references")

    print("✓ Reference evidence extraction working\n")


def test_summary_generation_fallback():
    """Test fallback summary generation."""
    print("Testing fallback summary generation...")

    mock_model = Mock()
    mock_context = Mock()
    mock_context.project_store = Mock()

    project_root = Path(__file__).parent.parent / "test_project"

    explorer = ExplorerAgent(
        model=mock_model,
        context=mock_context,
        project_root=project_root,
    )

    # Add some mock evidence
    from game_agent_try.agents.models import Evidence, Candidate

    explorer.evidence_items = [
        Evidence("e1", "unity_asset_search", "Found GameStateManager", 0.9, {}),
        Evidence("e2", "code_file_read", "Read GameStateManager.cs", 0.8, {}),
    ]

    explorer.candidate_nodes = [
        Candidate("n1", "Assets/Scripts/GameStateManager.cs", "CLASS", "GameStateManager", 0.9),
    ]

    explorer.rounds_used = 3
    explorer.tokens_used = 5000

    task = ExplorationTask(query="Find GameStateManager", max_results=10)

    # Generate fallback summary
    summary = explorer._generate_fallback_summary(task)

    assert "Find GameStateManager" in summary
    assert "2 pieces of evidence" in summary
    assert "3 rounds" in summary
    assert "5,000" in summary or "5000" in summary
    assert "GameStateManager" in summary
    print("  ✓ Fallback summary generated")
    print(f"  Summary preview: {summary[:100]}...")

    print("✓ Fallback summary generation working\n")


def test_summary_generation_llm():
    """Test LLM-based summary generation."""
    print("Testing LLM summary generation...")

    mock_model = Mock()
    mock_model.query = Mock(return_value={
        "content": "Found GameStateManager class in Assets/Scripts/GameStateManager.cs. It manages game state transitions including TransitionToWin method. PlayerController and UIManager reference this class.",
        "usage": {
            "prompt_tokens": 200,
            "completion_tokens": 100,
        },
    })

    mock_context = Mock()
    mock_context.project_store = Mock()

    project_root = Path(__file__).parent.parent / "test_project"

    explorer = ExplorerAgent(
        model=mock_model,
        context=mock_context,
        project_root=project_root,
    )

    # Add some mock evidence
    from game_agent_try.agents.models import Evidence, Candidate

    explorer.evidence_items = [
        Evidence("e1", "unity_asset_search", "Found GameStateManager", 0.9, {}),
    ]

    explorer.candidate_nodes = [
        Candidate("n1", "Assets/Scripts/GameStateManager.cs", "CLASS", "GameStateManager", 0.9),
    ]

    explorer.rounds_used = 2
    explorer.tokens_used = 3000

    task = ExplorationTask(query="Find GameStateManager", max_results=10)

    # Generate LLM summary
    summary = explorer._generate_summary(task)

    assert "GameStateManager" in summary
    assert len(summary) > 50  # Should be substantial
    print("  ✓ LLM summary generated")
    print(f"  Summary: {summary[:150]}...")

    # Check token tracking
    assert explorer.tokens_used == 3000 + 300  # Original + summary tokens
    print("  ✓ Summary token usage tracked")

    print("✓ LLM summary generation working\n")


def main():
    """Run all improved Explorer tests."""
    print("=" * 60)
    print("Testing Improved Explorer Functionality")
    print("=" * 60)
    print()

    try:
        test_tool_schema_loading()
        test_evidence_extraction_search()
        test_evidence_extraction_read()
        test_evidence_extraction_references()
        test_summary_generation_fallback()
        test_summary_generation_llm()

        print("=" * 60)
        print("✓ All Explorer improvements verified!")
        print("=" * 60)
        print()
        print("Summary of improvements:")
        print("  ✓ Real tool schemas loaded from ACI")
        print("  ✓ Smart evidence extraction (search/read/references)")
        print("  ✓ Candidate node extraction")
        print("  ✓ LLM-based summary generation")
        print("  ✓ Fallback summary for resilience")
        print()
        print("Explorer is now ready for real tasks!")

    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
