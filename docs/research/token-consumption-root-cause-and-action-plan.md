# Token Consumption Root Cause Analysis & Action Plan

## 🎯 Executive Summary

**Problem**: Agent consumed 112k tokens across 7 rounds to read 1 file, failed without completing task.

**Root Cause**: NOT a "round 7 spike" - cumulative inefficiency from 4 sources wasting **11,500 tokens per call (82% of input budget)**

**Solution**: 4 immediate fixes → 64% token reduction (14k → 5k per call)

---

## 📊 Token Waste Breakdown (Per Call)

| Component | Current | Root Cause | Optimized | Savings |
|-----------|---------|------------|-----------|---------|
| **Tool Schemas** | 3,310 | Exposing 11 tools simultaneously | 800 | -2,500 |
| **Evidence Items** | 7,200 | 36 items (12+12+12), never pruned | 2,000 | -5,200 |
| **Validation Logs** | 1,600 | 800-char summaries × 2 kept | 200 | -1,400 |
| **Working Set Details** | 3,600 | 3 details × 1,200 chars each | 1,200 | -2,400 |
| **TOTAL WASTE** | **15,710** | - | **4,200** | **-11,500** |

**Actual useful context**: ~2,500 tokens (plan, task, phase instructions)
**Wasted overhead**: ~11,500 tokens (73% waste rate)

---

## 🔍 Comparison with Mainstream Agents

| Agent | Tokens/Call | Strategy | Efficiency |
|-------|-------------|----------|------------|
| **Aider** | 4,000 | Repository map + lazy loading | ✅ Best |
| **SWE-agent** | 6,000 | Message truncation + stateful | ✅ Good |
| **OpenHands** | 6,500 | Multi-stage compression | ✅ Good |
| **Locus** | ~5,000 | Knowledge base + subagents | ✅ Good |
| **Ours (current)** | 14,000 | Virtual context (broken) | ❌ Poor |
| **Ours (fixed)** | 5,000 | 4 immediate fixes | ✅ Good |
| **Ours (optimal)** | 3,000 | + repo map + checkpoints | ✅✅ Excellent |

---

## 🛠️ Immediate Fixes (High Impact, Low Effort)

### Fix 1: Reduce Tool Schema Overhead (-2,500 tokens)

**File**: `src/game_agent/aci/controller.py`

**Problem**: Exposing 11 edit tools = 3,310 tokens (21% of budget)

**Solution**: Dynamic tool exposure - only 2-3 most relevant tools

```python
def _tool_exposure_for_phase(self, phase: str) -> list[str]:
    """Return minimal tool set for current phase."""
    
    if phase == "plan":
        return ["task_plan_submit"]
    
    elif phase == "explore":
        # Search tools only
        return [
            "unity_asset_search",
            "code_symbol_search", 
            "artifact_read",
        ]
    
    elif phase == "inspect":
        # Read tools only
        return [
            "candidate_read",
            "code_find_references",
            "unity_ref_search",
        ]
    
    elif phase == "diagnose":
        return ["diagnosis_submit"]
    
    elif phase in ["implementation", "edit"]:
        # Only 3 core edit tools instead of 11
        return [
            "unity_script_patch",      # Primary C# editing
            "code_diagnostics",        # Check compilation
            "submit_changes",          # Finalize
        ]
    
    elif phase == "validation":
        return [
            "unity_test_run",
            "validation_review",
            "submit_changes",
        ]
    
    else:
        # Fallback: essential tools only
        return ["artifact_read", "code_diagnostics"]
```

**Expected**: 3,310 → 800 tokens per call

---

### Fix 2: Aggressive Evidence Pruning (-5,200 tokens)

**File**: `src/game_agent/context/assembler.py`

**Problem**: 36 evidence items (12 verified + 12 observed + 12 suggested) sent every round, never pruned

**Solution**: Only include evidence referenced in last 2 tool calls + high-confidence items

```python
def _render_evidence(self) -> dict[str, Any]:
    """Render evidence with aggressive pruning."""
    
    # Get evidence IDs referenced in recent tool calls
    recent_evidence_ids = set()
    for tool in self._recent_tools[-2:]:  # Last 2 tools only
        recent_evidence_ids.update(tool.referenced_evidence_ids)
    
    # Verified: Only recent OR high-confidence
    verified = [
        item.to_dict()
        for item in self._evidence.verified()
        if item.id in recent_evidence_ids or item.confidence > 0.9
    ][-6:]  # Reduce from 12 to 6
    
    # Observed: Only recently referenced
    observed = [
        item.to_dict()
        for item in self._evidence.observed()
        if item.id in recent_evidence_ids
    ][-4:]  # Reduce from 12 to 4
    
    # Suggested: Only for current phase
    suggested = [
        item.to_dict()
        for item in self._evidence.suggested()
        if item.phase == self._current_phase and item.id in recent_evidence_ids
    ][-4:]  # Reduce from 12 to 4
    
    return {
        "verified": verified,    # 6 items max
        "observed": observed,    # 4 items max
        "suggested": suggested,  # 4 items max
        # Total: 14 items instead of 36
    }
```

**Expected**: 7,200 → 2,000 tokens per call

---

### Fix 3: Minimal Validation Summaries (-1,400 tokens)

**File**: `src/game_agent/context/assembler.py`

**Problem**: Each validation keeps 800-char summary, 2 summaries = 1,600 tokens

**Solution**: Success = minimal indicator, Failure = detailed summary

```python
def _record_validation(self, validation_type: str, success: bool, result: dict) -> None:
    """Record validation with minimal context overhead."""
    
    if success:
        # Success: Add to verified_facts, don't keep in recent_tools
        self._evidence.add_fact(
            claim=f"{validation_type} validation passed.",
            status=EvidenceStatus.RUNTIME_VERIFIED,
            source="validation",
        )
        # Don't append to recent_tools for successful validations
        return
    
    else:
        # Failure: Keep detailed summary in recent_tools
        summary = self._format_validation_failure(validation_type, result)
        observation = ToolObservation(
            tool=validation_type,
            summary=summary,  # Detailed only for failures
            result=result,
        )
        self._recent_tools.append(observation)
```

**Expected**: 1,600 → 200 tokens per call (only failures have details)

---

### Fix 4: Reduce Working Set Detail Size (-2,400 tokens)

**File**: `src/game_agent/context/models.py` and `assembler.py`

**Problem**: 3 details × 1,200 chars = 3,600 chars minimum

**Solution**: Show structure preview, not full content

```python
class ContextConfig(BaseModel):
    # ... existing fields ...
    
    detail_char_limit: int = Field(default=600, ge=128)  # Reduce from 1,200
    detail_preview_only: bool = Field(default=True)      # New: structure only

def _format_candidate_detail(self, candidate: Candidate, preview_only: bool = True) -> dict:
    """Format candidate with size control."""
    
    if preview_only:
        # Lightweight structure view
        return {
            "id": candidate.id,
            "kind": candidate.kind,
            "name": candidate.name,
            "path": candidate.path,
            "summary": candidate.summary[:200] if candidate.summary else "",
            "detail_available": True,  # Indicator that full detail exists
        }
    else:
        # Full detail (only on explicit request)
        return candidate.to_dict(char_limit=600)  # Still reduced from 1,200
```

**Expected**: 3,600 → 1,200 tokens per call

---

## 📈 Expected Impact

### Token Reduction

| Scenario | Current | After Fixes | Improvement |
|----------|---------|-------------|-------------|
| Tokens per call | 14,000 | 5,000 | -64% |
| Rounds before limit | 7-9 | 20-25 | +185% |
| Simple task (1-file fix) | ❌ Failed | ✅ Completes in 4-6 rounds | Success |
| Complex task (3-file edit) | ❌ Failed | ✅ Completes in 10-15 rounds | Success |

### Task Completion Rate

| Task Type | Before | After | Example |
|-----------|--------|-------|---------|
| Simple bug fix | 0% | >80% | Missing event call |
| UI state management | 0% | >70% | Show/hide screens |
| Multi-file refactor | 0% | >50% | Rename + update refs |

---

## 🏗️ Architecture Improvements (Medium-term)

### 1. Aider-Style Repository Map

Replace full candidate details with lightweight structural overview:

```python
# New: src/game_agent/context/repository_map.py

class RepositoryMap:
    """Generate lightweight project structure overview (500-1000 tokens)."""
    
    def build_map(self, working_set: TaskWorkingSet, graph: ProjectGraph) -> str:
        """Build map from working set + project graph."""
        
        map_sections = []
        
        # Unity scenes
        scenes = graph.get_nodes_by_kind(NodeKind.UNITY_SCENE)
        map_sections.append(self._format_scenes(scenes[:5]))
        
        # Scripts by category
        scripts = working_set.get_candidates(kind="script")
        grouped = self._group_by_directory(scripts)
        map_sections.append(self._format_scripts(grouped))
        
        # Active candidates (currently being worked on)
        active = working_set.get_active_candidates()
        map_sections.append(self._format_active(active))
        
        return "\n\n".join(map_sections)
    
    def _format_scripts(self, grouped: dict[str, list[Candidate]]) -> str:
        """Format scripts by directory with signatures."""
        lines = ["# Scripts"]
        for directory, scripts in grouped.items():
            lines.append(f"## {directory}/")
            for script in scripts[:10]:  # Max 10 per directory
                signature = self._get_signature(script)
                lines.append(f"  - {script.name} {signature}")
        return "\n".join(lines)
    
    def _get_signature(self, candidate: Candidate) -> str:
        """Get class/method signature from graph."""
        # Example: "[MonoBehaviour] 3 methods, 2 fields"
        # Or: "[static class] 5 utility methods"
        ...
```

**Usage**:
```python
# In context assembly
repository_map = self.repo_map.build_map(self.working_set, self.graph)

context_payload = {
    "repository_map": repository_map,  # ~800 tokens
    "active_files": [...],             # Only files being edited
    # Remove: candidate_details (was 3,600 tokens)
}
```

**Impact**: 3,600 → 800 tokens per call

---

### 2. Session Checkpointing

Serialize context state, clear message history:

```python
# New: src/game_agent/context/checkpoint.py

class ContextCheckpoint:
    """Serialize/restore context state to manage token growth."""
    
    def save(self, assembler: ContextAssembler, path: Path) -> None:
        """Save current state to disk."""
        state = {
            "evidence_ledger": assembler.evidence.to_dict(),
            "working_set": assembler.working_set.to_dict(),
            "memory": assembler.memory.to_dict(),
            "phase": assembler.phase,
            "plan": assembler.plan.to_dict() if assembler.plan else None,
            "verified_facts": assembler.verified_facts,
            "changed_files": assembler.changed_files,
        }
        path.write_text(json.dumps(state, indent=2))
    
    def restore(self, path: Path) -> ContextState:
        """Load state from disk."""
        state = json.loads(path.read_text())
        return ContextState.from_dict(state)

# In baseline_runner.py or agent loop:
checkpoint_manager = ContextCheckpoint()

for round_num in range(max_rounds):
    # Every 5 rounds or at phase transitions
    if round_num % 5 == 0 and round_num > 0:
        checkpoint_path = artifact_dir / f"checkpoint_round_{round_num}.json"
        checkpoint_manager.save(context_assembler, checkpoint_path)
        
        # Clear message history, restore from checkpoint
        context_assembler.clear_message_history()
        context_assembler.restore_state(checkpoint_path)
        
        # Continue with fresh context but preserved state
```

**Impact**: Reset cumulative token growth every 5 rounds while maintaining state

---

### 3. Lazy Evidence Loading

Don't include evidence in every call - load on demand:

```python
# In context assembly
context_payload = {
    # Instead of full evidence (7,200 tokens):
    "evidence_summary": {
        "verified_count": 3,
        "verified_ids": ["ev_001", "ev_002", "ev_003"],
        "observed_count": 2,
        "observed_ids": ["ev_010", "ev_011"],
    },
    # ~100 tokens instead of 7,200
}

# Add new tool for explicit evidence retrieval
@tool
def evidence_read(evidence_id: str) -> dict:
    """Retrieve specific evidence item when needed.
    
    Use when you need details of a specific evidence item.
    Evidence IDs are shown in evidence_summary.
    """
    return context_assembler.evidence.get(evidence_id).to_dict()
```

**Impact**: 7,200 → 100 tokens baseline, +200 tokens on-demand when needed

---

## 📋 Implementation Priority

### Priority 1: Immediate Fixes (This Week)

1. ✅ **Tool schema reduction** - 1 hour
   - Modify `aci/controller.py` tool exposure logic
   - Test with optimized config

2. ✅ **Evidence pruning** - 2 hours
   - Modify `context/assembler.py` evidence rendering
   - Add reference tracking

3. ✅ **Validation summaries** - 1 hour  
   - Modify validation recording logic
   - Test success/failure cases

4. ✅ **Working set details** - 1 hour
   - Add preview mode to candidate formatting
   - Update config defaults

**Total effort**: 5 hours
**Expected result**: 64% token reduction, tasks complete successfully

---

### Priority 2: Architecture (Next 2 Weeks)

1. **Repository map** - 1 day
   - Implement map builder
   - Integrate into context assembly
   - Test with various project sizes

2. **Session checkpointing** - 1 day
   - Implement checkpoint save/restore
   - Add to agent loop
   - Test state persistence

3. **Lazy evidence loading** - 0.5 day
   - Add evidence_read tool
   - Modify context payload
   - Test on-demand loading

**Total effort**: 2.5 days
**Expected result**: Additional 40% reduction (5k → 3k tokens/call)

---

### Priority 3: Long-term (Future)

1. **Knowledge base system** (like Locus)
   - Cache learned patterns ("Unity UI update flow")
   - Reduce exploration for similar tasks
   - Estimated: 1-2 weeks

2. **Multi-agent delegation**
   - Coordinator + specialist agents
   - Research subagent for exploration
   - Estimated: 2-3 weeks

---

## 🧪 Validation Plan

### Test Suite

Create benchmark tasks with known token budgets:

```python
# tests/test_token_efficiency.py

BENCHMARK_TASKS = [
    {
        "name": "simple_bug_fix",
        "description": "Missing event call in state transition",
        "target_tokens": 25_000,  # Should complete in 5 rounds × 5k
        "max_tokens": 40_000,
    },
    {
        "name": "ui_state_management",
        "description": "Show/hide UI screens on state change",
        "target_tokens": 40_000,  # Should complete in 8 rounds × 5k
        "max_tokens": 60_000,
    },
    {
        "name": "multi_file_refactor",
        "description": "Rename method + update references",
        "target_tokens": 60_000,  # Should complete in 12 rounds × 5k
        "max_tokens": 80_000,
    },
]

def test_token_efficiency():
    for task in BENCHMARK_TASKS:
        result = run_agent_with_task(task["description"])
        
        assert result.total_tokens < task["max_tokens"], \
            f"Task '{task['name']}' exceeded token budget"
        
        assert result.exit_status == "Submitted", \
            f"Task '{task['name']}' failed to complete"
        
        avg_tokens_per_round = result.total_tokens / result.rounds
        assert avg_tokens_per_round < 6_000, \
            f"Task '{task['name']}' has inefficient token usage"
```

### Metrics to Track

| Metric | Current | Target | Measurement |
|--------|---------|--------|-------------|
| Avg tokens/round | 14,000 | < 6,000 | events.jsonl model_usage |
| Task completion rate | 0% | > 70% | exit_status == "Submitted" |
| Rounds to completion | N/A (failed) | 4-6 (simple), 10-15 (complex) | rounds count |
| Tool schema overhead | 21% | < 10% | tool_schema_tokens / prompt_tokens |
| Evidence overhead | 51% | < 20% | evidence_tokens / prompt_tokens |

---

## 📚 Lessons from Other Agents

### What We're Doing Right ✅

1. **Virtual context assembly** - Similar to SWE-agent's stateful approach
2. **Project graph** - Like Aider's repository awareness
3. **Dynamic tool exposure** - Like OpenHands' phase-based tools
4. **Evidence artifacts** - Similar to memory systems in Locus

### What We're Missing ❌

1. **Aggressive pruning** - Other agents keep 2-3 messages, we keep 17
2. **Lightweight overviews** - Aider uses 800-token maps, we use 3,600-token details
3. **Lazy loading** - Other agents load on demand, we load everything
4. **Checkpointing** - Long-running agents serialize state, we accumulate context

### Key Insight from Locus

> *"Try not to analyze large numbers of files directly in the main context"*

**Locus approach**:
- Main agent: Coordination + decision-making (small context)
- Explorer subagent: Research + file analysis (isolated context)
- Knowledge base: Cached patterns (zero exploration cost for similar tasks)

**Our current approach**:
- Single agent does everything
- All research happens in main context
- Every task starts from scratch

**Recommendation**: Implement subagent delegation for research-heavy phases

---

## 🎯 Success Criteria

### Week 1 (Immediate Fixes)

- [ ] Avg tokens/call: 14k → 5k ✅
- [ ] Simple task completes: ❌ → ✅
- [ ] Tool schema: 3,310 → 800 tokens
- [ ] Evidence: 7,200 → 2,000 tokens

### Week 3 (Architecture Improvements)

- [ ] Avg tokens/call: 5k → 3k ✅
- [ ] Complex task completes: ❌ → ✅  
- [ ] Repository map implemented
- [ ] Checkpointing working

### Month 2 (Knowledge Base)

- [ ] Similar task: Skip 3-4 exploration rounds
- [ ] Total tokens: 40-50% reduction vs baseline
- [ ] Task completion rate: > 80%

---

## 🔗 References

- **Agent research findings**: `docs/research/token-consumption-analysis-agent-report.txt`
- **Locus context strategy**: `references/Locus-main/agent/dev/rule/`
- **Current implementation**: `src/game_agent/context/assembler.py`
- **Baseline results**: `artifacts/baselines/state-event-v1/optimized-run1-*/`

---

## Conclusion

**Root cause identified**: NOT a mysterious "round 7 spike", but systematic inefficiency from:
1. Tool schema bloat (3,310 tokens)
2. Evidence accumulation (7,200 tokens)
3. Verbose validation logs (1,600 tokens)
4. Oversized working set details (3,600 tokens)

**Total waste**: 11,500 tokens per call (82% of budget wasted on overhead)

**Solution**: 4 immediate fixes → 64% reduction → tasks complete successfully

**Next level**: Architecture improvements → 40% additional reduction → match best agents

The agent framework is fundamentally sound (virtual context + graph + evidence). The problem is configuration and pruning, not architecture. With immediate fixes, we'll be competitive with mainstream agents. With architecture improvements, we'll exceed them.
