"""Explorer Agent: Isolated exploration with clean context.

The Explorer is responsible for:
- Running in a clean, isolated context
- Only exposing search/read tools (no mutation)
- Collecting evidence through exploration
- Returning structured evidence packages
- NOT diagnosing or modifying code
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from game_agent_try.aci.query import StructuredQueryExecutor
from game_agent_try.aci.schemas import QUERY_TOOL_NAMES, STRUCTURED_QUERY_TOOLS
from game_agent_try.agents.models import (
    Candidate,
    Evidence,
    EvidencePackage,
    ExplorationTask,
)
from game_agent_try.context import ContextAssembler, EvidenceLedger
from game_agent_try.framework import Environment, Model


# Explorer只暴露查询工具（不包括candidate_read，它需要Controller的候选管理）
EXPLORER_TOOL_NAMES = {
    "unity_editor_status",
    "unity_asset_search",
    "unity_ref_search",
    "unity_object_list",
    "unity_object_search",
    "unity_object_read",
    "code_symbol_search",
    "code_find_references",
    "unity_asset_read",
    "code_file_read",
    "code_diagnostics",
    "artifact_read",
}


class ExplorerAgent:
    """Agent that explores the codebase in isolation and returns evidence.

    Key characteristics:
    - Clean context initialization (no history pollution)
    - Read-only operations (search + read)
    - Structured evidence output
    - Token-bounded exploration
    """

    def __init__(
        self,
        model: Model,
        context: ContextAssembler,
        project_root: Path,
        artifact_root: Path | None = None,
        max_rounds: int = 10,
        max_tokens: int = 60_000,  # Increased from 40k to 60k for better coverage
    ):
        """Initialize the Explorer agent.

        Args:
            model: LLM model for exploration
            context: Context assembler with project graph
            project_root: Unity project root
            artifact_root: Artifact storage directory
            max_rounds: Maximum exploration rounds
            max_tokens: Maximum token budget for exploration (default 60k)
        """
        self.model = model
        self.context = context
        self.project_root = project_root.resolve()
        self.artifact_root = (
            artifact_root.resolve()
            if artifact_root is not None
            else self.project_root / ".game-agent-artifacts"
        )
        self.max_rounds = max_rounds
        self.max_tokens = max_tokens

        # Query executor for structured searches
        self.query_executor = StructuredQueryExecutor(
            context,
            project_root=project_root,
            artifact_root=artifact_root,
        )

        # Clean message history
        self.messages: list[dict[str, Any]] = []

        # Collected evidence
        self.evidence_items: list[Evidence] = []
        self.candidate_nodes: list[Candidate] = []

        # Statistics
        self.rounds_used = 0
        self.tokens_used = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

        self.logger = logging.getLogger("explorer")

    def explore(self, task: ExplorationTask) -> EvidencePackage:
        """Run exploration to find evidence for the task.

        Args:
            task: Exploration task specification

        Returns:
            Structured evidence package with findings
        """
        self.logger.info(f"Starting exploration: {task.query}")
        self._reset_state()

        # Initialize with system prompt
        system_prompt = self._build_system_prompt()
        self.messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": self._build_exploration_prompt(task)},
        ]

        try:
            # Exploration loop
            for round_num in range(task.max_rounds):
                self.rounds_used = round_num + 1

                # Check token budget
                if self.tokens_used >= self.max_tokens:
                    self.logger.warning(f"Token budget exhausted: {self.tokens_used}/{self.max_tokens}")
                    break

                # Get model response
                response = self._call_model()

                if response is None:
                    break

                # Debug: log response structure
                self.logger.info(f"Response keys: {list(response.keys())}")
                self.logger.info(f"Has tool_calls: {response.get('tool_calls') is not None}")
                if response.get('tool_calls'):
                    self.logger.info(f"Tool calls count: {len(response.get('tool_calls', []))}")
                    self.logger.info(f"First tool call: {response.get('tool_calls', [{}])[0] if response.get('tool_calls') else 'None'}")

                # Process tool calls
                if not response.get("tool_calls"):
                    # No more exploration needed
                    self.logger.info("Explorer finished (no more tool calls)")
                    break

                # Execute tools and collect evidence
                tool_results = self._execute_tools(response["tool_calls"])

                # Add to message history
                self.messages.append({
                    "role": "assistant",
                    "content": response.get("content", ""),
                    "tool_calls": response["tool_calls"],
                })

                # Add tool results as individual tool messages
                for result in tool_results:
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": result.get("tool_call_id", ""),
                        "content": result.get("output", ""),
                    })

                # Check if we have enough evidence
                if len(self.evidence_items) >= task.max_results:
                    self.logger.info(f"Collected enough evidence: {len(self.evidence_items)}")
                    break

            # Generate summary
            summary = self._generate_summary(task)

            return EvidencePackage(
                success=True,
                evidence_items=self.evidence_items,
                candidate_nodes=self.candidate_nodes,
                summary=summary,
                tokens_used=self.tokens_used,
                rounds_used=self.rounds_used,
                search_strategy=task.strategy,
                error=None,
            )

        except Exception as e:
            self.logger.error(f"Exploration failed: {e}", exc_info=True)
            return EvidencePackage(
                success=False,
                evidence_items=self.evidence_items,
                candidate_nodes=self.candidate_nodes,
                summary="",
                tokens_used=self.tokens_used,
                rounds_used=self.rounds_used,
                search_strategy=task.strategy,
                error=str(e),
            )

    def _reset_state(self) -> None:
        """Reset exploration state for a new task."""
        self.messages = []
        self.evidence_items = []
        self.candidate_nodes = []
        self.rounds_used = 0
        self.tokens_used = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def _build_system_prompt(self) -> str:
        """Build system prompt for Explorer."""
        return """You are an Explorer agent. Your role is to search and collect evidence EFFICIENTLY.

Your responsibilities:
- Search the Unity project for relevant code and assets
- Read files and understand their structure
- Collect evidence about what exists and how it's connected
- Return structured findings

What you CANNOT do:
- Diagnose problems (leave that to the Coordinator)
- Modify code (no mutations)
- Make recommendations (just collect facts)

Available tools (USE EXACT NAMES):
- code_symbol_search: Search for C# classes/methods/fields by name or pattern
- code_find_references: Find what calls/uses a symbol
- code_file_read: Read C# file content
- unity_asset_search: Search for Unity assets (scenes, prefabs, etc.)
- unity_ref_search: Find Unity asset references
- unity_object_read: Read Unity object/component data

EFFICIENT STRATEGY (minimize token usage):
1. Start with 2-3 PRECISE code searches (not broad searches)
   - Use code_symbol_search for class/method names
   - Example: search for "GameStateManager", "TutorialUI", "Hide"

2. Use code_find_references on top results (cheap and effective)
   - Find what calls the methods you found
   - Example: who calls TutorialUI.Hide()?

3. Read ONLY the most relevant 3-5 files with code_file_read
   - Focus on files mentioned in the query
   - Skip obvious framework code

4. Stop early if you have 5-8 strong candidates (don't waste tokens)

Focus on FACTS, not interpretations. Be EFFICIENT with token usage.
USE EXACT TOOL NAMES from the list above."""

    def _build_exploration_prompt(self, task: ExplorationTask) -> str:
        """Build the exploration task prompt."""
        return f"""Explore the codebase to find evidence for this query:

{task.query}

TARGET: Find up to {task.max_results} relevant pieces of evidence.
BUDGET: You have {task.max_rounds} rounds. Use them wisely.

CRITICAL: Be EFFICIENT - minimize token usage:
- Start with 2-3 PRECISE searches (specific class/method names)
- Use ref_search on top results (cheap and effective)
- Read ONLY the most relevant 3-5 files
- STOP when you have 5-8 strong candidates

Example efficient flow:
1. unity_code_search for specific terms (e.g., "GameStateManager", "TutorialUI")
2. unity_ref_search on the best results
3. unity_node_read on 3-5 key files
4. Done!

Start exploring now - BE EFFICIENT!"""

    def _call_model(self) -> dict[str, Any] | None:
        """Call the LLM model and track tokens."""
        try:
            # Set available tools for this model call
            # Note: LitellmModel already passes tools internally,
            # so we just set which tools are available
            if hasattr(self.model, 'set_available_tool_names'):
                self.model.set_available_tool_names(tuple(EXPLORER_TOOL_NAMES))

            # Call model without passing tools (model handles it internally)
            response = self.model.query(
                messages=self.messages,
            )

            # Track tokens - usage is in response["extra"]
            extra = response.get("extra", {})
            prompt_tokens = extra.get("prompt_tokens", 0)
            completion_tokens = extra.get("completion_tokens", 0)

            self.prompt_tokens += prompt_tokens
            self.completion_tokens += completion_tokens
            self.tokens_used = self.prompt_tokens + self.completion_tokens

            return response

        except Exception as e:
            self.logger.error(f"Model call failed: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return None

    def _get_tool_schemas(self) -> list[dict[str, Any]]:
        """Get tool schemas for Explorer (read-only tools)."""
        # Load from ACI STRUCTURED_QUERY_TOOLS
        explorer_tools = []

        for tool in STRUCTURED_QUERY_TOOLS:
            tool_name = tool["function"]["name"]

            # Only include Explorer-allowed tools
            if tool_name in EXPLORER_TOOL_NAMES:
                explorer_tools.append(tool)

        return explorer_tools

    def _execute_tools(self, tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Execute tool calls and collect evidence."""
        results = []

        self.logger.info(f"Executing {len(tool_calls)} tool calls...")

        for tool_call in tool_calls:
            tool_name = tool_call.get("function", {}).get("name", "")
            tool_call_id = tool_call.get("id", "")

            self.logger.info(f"  Tool: {tool_name}, ID: {tool_call_id}")

            # Only allow Explorer tools
            if tool_name not in EXPLORER_TOOL_NAMES:
                self.logger.warning(f"  Tool {tool_name} not allowed in Explorer")
                results.append({
                    "tool_call_id": tool_call_id,
                    "output": json.dumps({
                        "error": f"Tool {tool_name} not available in Explorer"
                    }),
                })
                continue

            # Parse arguments (might be string or dict)
            arguments = tool_call.get("function", {}).get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                    self.logger.info(f"  Parsed arguments from string")
                except json.JSONDecodeError as e:
                    self.logger.error(f"  Failed to parse arguments: {e}")
                    results.append({
                        "tool_call_id": tool_call_id,
                        "output": json.dumps({
                            "error": f"Invalid arguments: {e}"
                        }),
                    })
                    continue

            self.logger.info(f"  Arguments: {arguments}")

            # Execute query tool
            action = {
                "tool": tool_name,
                "arguments": arguments,
            }

            try:
                result = self.query_executor.execute(action)
                self.logger.info(f"  Result status: {result.get('status')}")
                self.logger.info(f"  Result keys: {list(result.keys())}")

                # Debug: print first 200 chars of result
                result_str = json.dumps(result, indent=2)[:200]
                self.logger.info(f"  Result preview: {result_str}...")

                # Extract evidence from result
                self._extract_evidence(tool_name, result)
                self.logger.info(f"  Evidence count: {len(self.evidence_items)}, Candidates: {len(self.candidate_nodes)}")

                results.append({
                    "tool_call_id": tool_call_id,
                    "output": json.dumps(result),
                })

            except Exception as e:
                self.logger.error(f"  Tool execution failed: {e}")
                import traceback
                traceback.print_exc()
                results.append({
                    "tool_call_id": tool_call_id,
                    "output": json.dumps({
                        "error": str(e)
                    }),
                })

        return results

    def _extract_evidence(self, tool_name: str, result: dict[str, Any]) -> None:
        """Extract evidence items from tool result.

        Query tools return: {"output": json_string, "returncode": 0, "extra": {"structured": actual_result}}
        The actual query result is in extra["structured"]
        """
        # Get the structured result from extra
        extra = result.get("extra", {})
        structured = extra.get("structured", {})

        if not structured or structured.get("status") == "error":
            self.logger.warning(f"Tool {tool_name} returned error or empty result")
            return

        evidence_id = hashlib.md5(
            f"{tool_name}:{json.dumps(structured)}".encode()
        ).hexdigest()[:12]

        # Extract based on tool type
        if tool_name in {"unity_asset_search", "code_symbol_search", "unity_object_search"}:
            # Search tools return nodes
            nodes = structured.get("nodes", []) or structured.get("results", [])

            if nodes:
                # Create evidence for search results
                node_summaries = []
                for node in nodes[:5]:  # Top 5 results
                    node_id = node.get("id", "")
                    node_kind = node.get("kind", "")
                    node_path = node.get("path", "")
                    node_name = node.get("name", "")

                    node_summaries.append(f"{node_kind}: {node_path or node_name}")

                    # Create candidate node
                    self.candidate_nodes.append(Candidate(
                        node_id=node_id,
                        path=node_path,
                        role=node_kind,
                        summary=node_name or node_path,
                        confidence=0.8,  # Default confidence
                        evidence_ids=[evidence_id],
                    ))

                self.evidence_items.append(Evidence(
                    evidence_id=evidence_id,
                    source=tool_name,
                    content="\n".join(node_summaries),
                    relevance_score=0.9 if len(nodes) > 0 else 0.5,
                    metadata={
                        "tool": tool_name,
                        "result_count": len(nodes),
                        "query": structured.get("query", ""),
                    },
                ))

        elif tool_name in {"code_file_read", "unity_asset_read", "unity_object_read"}:
            # Read tools return content in output
            output_str = result.get("output", "")

            # Try to parse the output as JSON
            try:
                output_data = json.loads(output_str) if isinstance(output_str, str) else output_str
                content = output_data.get("content", "") if isinstance(output_data, dict) else str(output_data)
            except:
                content = output_str

            path = structured.get("path", "") or structured.get("asset_path", "")

            # Extract artifact information from extra
            extra = result.get("extra", {})
            artifact_path = extra.get("evidence_artifact_path", "")
            artifact_sha256 = extra.get("evidence_artifact_sha256", "")

            if content:
                # Truncate long content for evidence
                truncated_content = content[:500] + "..." if len(content) > 500 else content

                metadata = {
                    "tool": tool_name,
                    "path": path,
                    "full_length": len(content),
                    "sha256": structured.get("sha256", ""),
                }

                # Add artifact info to metadata
                if artifact_path:
                    metadata["artifact_path"] = artifact_path
                if artifact_sha256:
                    metadata["artifact_sha256"] = artifact_sha256

                self.evidence_items.append(Evidence(
                    evidence_id=evidence_id,
                    source=tool_name,
                    content=f"Read {path}:\n{truncated_content}",
                    relevance_score=0.85,
                    metadata=metadata,
                ))

        elif tool_name in {"unity_ref_search", "code_find_references"}:
            # Reference search returns relationships
            rows = structured.get("rows", [])

            if rows:
                ref_summaries = []
                for row in rows[:10]:  # Top 10 references
                    source = row.get("source", {})
                    target = row.get("target", {})
                    edge_kind = row.get("edge_kind", "")

                    source_name = source.get("name", source.get("path", ""))
                    target_name = target.get("name", target.get("path", ""))

                    ref_summaries.append(f"{source_name} --{edge_kind}--> {target_name}")

                self.evidence_items.append(Evidence(
                    evidence_id=evidence_id,
                    source=tool_name,
                    content="\n".join(ref_summaries),
                    relevance_score=0.8,
                    metadata={
                        "tool": tool_name,
                        "reference_count": len(rows),
                    },
                ))

        elif tool_name == "unity_editor_status":
            # Status tool returns metadata
            status = structured.get("editor_state", "unknown")
            capabilities = structured.get("capabilities", {})

            self.evidence_items.append(Evidence(
                evidence_id=evidence_id,
                source=tool_name,
                content=f"Unity Editor: {status}, Capabilities: {json.dumps(capabilities)}",
                relevance_score=0.3,  # Low relevance for status
                metadata={
                    "tool": tool_name,
                    "status": status,
                },
            ))

        else:
            # Generic fallback
            self.evidence_items.append(Evidence(
                evidence_id=evidence_id,
                source=tool_name,
                content=json.dumps(structured, indent=2)[:500],
                relevance_score=0.5,
                metadata={"tool": tool_name},
            ))

    def _generate_summary(self, task: ExplorationTask) -> str:
        """Generate a summary of exploration findings using LLM.

        Args:
            task: Original exploration task

        Returns:
            200-300 word summary of findings
        """
        if not self.evidence_items:
            return "No evidence found during exploration."

        # Build summary prompt
        evidence_summary = []
        for idx, evidence in enumerate(self.evidence_items[:10], 1):
            evidence_summary.append(
                f"{idx}. [{evidence.source}] (relevance: {evidence.relevance_score:.2f})\n"
                f"   {evidence.content[:200]}..."
            )

        candidate_summary = []
        for idx, candidate in enumerate(self.candidate_nodes[:5], 1):
            candidate_summary.append(
                f"{idx}. {candidate.role}: {candidate.path or candidate.summary}"
            )

        summary_prompt = f"""Summarize the exploration findings in 200-300 words.

Original Query: {task.query}

Evidence Found ({len(self.evidence_items)} items):
{chr(10).join(evidence_summary)}

Candidate Nodes ({len(self.candidate_nodes)} items):
{chr(10).join(candidate_summary)}

Statistics:
- Rounds used: {self.rounds_used}/{task.max_rounds}
- Tokens used: {self.tokens_used}
- Evidence items: {len(self.evidence_items)}
- Candidate nodes: {len(self.candidate_nodes)}

Provide a concise summary of:
1. What was found (key files, classes, methods)
2. How components relate to each other
3. Relevant patterns or structures discovered

Keep it factual and concrete. Focus on what exists, not interpretations."""

        try:
            # Call LLM to generate summary (no tools needed)
            # Temporarily set available tools to None to prevent tools from being sent
            original_tools = None
            original_available = None
            if hasattr(self.model, 'agent_tools'):
                original_tools = self.model.agent_tools
                self.model.agent_tools = None  # Set to None instead of []
            if hasattr(self.model, 'available_tool_names'):
                original_available = self.model.available_tool_names
                self.model.available_tool_names = None

            response = self.model.query(
                messages=[
                    {"role": "system", "content": "You are a technical summarizer. Provide concise, factual summaries."},
                    {"role": "user", "content": summary_prompt},
                ],
            )

            # Restore original tools
            if original_tools is not None:
                self.model.agent_tools = original_tools
            if original_available is not None:
                self.model.available_tool_names = original_available

            summary = response.get("content", "").strip()

            # Track tokens used for summary generation - usage is in extra
            extra = response.get("extra", {})
            summary_tokens = extra.get("prompt_tokens", 0) + extra.get("completion_tokens", 0)
            self.tokens_used += summary_tokens
            self.prompt_tokens += extra.get("prompt_tokens", 0)
            self.completion_tokens += extra.get("completion_tokens", 0)

            return summary if summary else self._generate_fallback_summary(task)

        except Exception as e:
            self.logger.warning(f"LLM summary generation failed: {e}, using fallback")
            return self._generate_fallback_summary(task)

    def _generate_fallback_summary(self, task: ExplorationTask) -> str:
        """Generate a template-based summary as fallback.

        Args:
            task: Original exploration task

        Returns:
            Basic summary without LLM
        """
        summary_lines = [
            f"Exploration Results for: {task.query}",
            "",
            f"Found {len(self.evidence_items)} pieces of evidence across {self.rounds_used} rounds.",
            "",
        ]

        if self.candidate_nodes:
            summary_lines.append("Key Candidates:")
            for idx, candidate in enumerate(self.candidate_nodes[:5], 1):
                summary_lines.append(f"  {idx}. {candidate.role}: {candidate.path or candidate.summary}")
            summary_lines.append("")

        if self.evidence_items:
            summary_lines.append("Evidence Sources:")
            source_counts = {}
            for evidence in self.evidence_items:
                source_counts[evidence.source] = source_counts.get(evidence.source, 0) + 1

            for source, count in sorted(source_counts.items(), key=lambda x: -x[1]):
                summary_lines.append(f"  - {source}: {count} items")
            summary_lines.append("")

        summary_lines.extend([
            "Statistics:",
            f"  - Rounds: {self.rounds_used}/{task.max_rounds}",
            f"  - Tokens: {self.tokens_used:,}",
            f"  - Evidence: {len(self.evidence_items)} items",
            f"  - Candidates: {len(self.candidate_nodes)} nodes",
        ])

        return "\n".join(summary_lines)
