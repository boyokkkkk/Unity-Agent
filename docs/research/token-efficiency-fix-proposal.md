# Token 效率问题完整修复方案

## 诊断时间
2026-08-01

## 执行摘要

基于对 `ablation-group1-run2` 的深入分析，发现创新点（Evidence Artifacts、Context Compression 等）**未能真正节省 token**。本文档提供经过充分诊断的修复方案，避免冗余设计，确保与现有系统兼容。

---

## 第一部分：问题诊断

### 1.1 核心问题确认

**问题 1: Agent 使用原始 messages 而非 assembled messages**

**证据**：
```python
# default.py:404-441
model_messages = self.context_assembler.assemble(self.messages, ...)
message = self.model.query(model_messages, ...)  # ✅ 正确使用 assembled
```

**结论**：✅ **此问题不存在**。Agent 确实使用了 assembled messages。

---

**问题 2: Evidence Artifact 创建率低**

**证据**：
- 实际运行只创建了 1 个 artifact (5.6KB)
- 从 `query.py:282-296` 看到代码**已经实现** artifact 创建：
  ```python
  def _code_file_read(self, args):
      # ...
      if self.artifact_root:
          artifact_dir = self.artifact_root / "evidence-artifacts"
          artifact_file = artifact_dir / f"{evidence_id.replace(':', '_')}.txt"
          artifact_file.write_text(full_content, encoding="utf-8")  # ✅ 已实现
          artifact_relative = artifact_file.relative_to(self.artifact_root).as_posix()
  ```

**但是**：从 `query.py:299` 继续看，返回值中**没有包含** `evidence_artifact_path`：
```python
payload = {
    "status": "ok",
    "node": ...,
    "content": content[:maximum],
    # ❌ 缺少: "evidence_artifact_path": artifact_relative
}
```

**结论**：✅ **artifact 创建代码存在，但返回值中缺少字段**。这导致 assembler 无法识别 artifact。

---

**问题 3: Context Compression 是假的**

**证据**：
```python
# assembler.py:522-534
def _compress(self, reasons):
    if len(self.recent_tools) > self.config.max_recent_tool_results:
        removed = self.recent_tools[: -self.config.max_recent_tool_results or None]
        self.recent_tools = self.recent_tools[-self.config.max_recent_tool_results :]
```

这只是移除了 `recent_tools` 列表中的引用，但：
- 从 `assembler.py:635` 看到：`recent_tools = [item.to_dict() for item in self.recent_tools[-self.config.max_recent_tool_results :]]`
- 这些 tool results 会被 **重新序列化到虚拟上下文的 JSON 中**

**关键发现**：从 `default.py:404` 看到：
```python
model_messages = self.context_assembler.assemble(self.messages, ...)
```

`self.messages` 是原始历史，但 `assemble()` 返回的是：
```python
# assembler.py:287
return [system, {"role": "user", "content": view, "extra": {"virtual_context": True}}]
```

**只有 2 条消息**！所以原始 messages 并没有被发送给模型。

**结论**：✅ **Compression 是真的**，但需要验证 `recent_tools` 的内容大小。

---

**问题 4: Token 增长的真正原因**

重新分析 token 增长：
- Round 1: 873 tokens
- Round 2: 3,878 tokens (+3,005)
- Round 6: 16,223 tokens

每轮增长 ~3,000 tokens，来源：
1. **新的 candidate_details** (max 1 个，但 `detail_char_limit: 800`)
2. **新的 working_set entries** (从 1 增长到 4)
3. **新的 evidence items** (从 0 增长到多个)
4. **recent_tool_results** (max 1 个，但可能很大)

**关键洞察**：`detail_char_limit: 800` 只限制了 JSON 序列化后的长度，但：
- 从 `assembler.py:519`：`_bounded_json(detail, self.config.detail_char_limit)`
- 如果 detail 本身是嵌套结构（包含完整文件内容），截断后仍可能很大

---

### 1.2 根本原因总结

| 问题 | 是否存在 | 严重性 | 需要修复 |
|------|---------|--------|---------|
| Agent 使用原始 messages | ❌ 不存在 | N/A | 否 |
| Evidence artifact 返回值缺失 | ✅ 存在 | 高 | **是** |
| Compression 是假的 | ❌ 不存在 | N/A | 否 |
| Candidate details 过大 | ✅ 存在 | 中 | **是** |
| Working set 配置太激进 | ✅ 存在 | 高 | **是** |
| Tool results 内容过大 | ⚠️ 可能 | 中 | **是** |

---

## 第二部分：修复方案

### 原则

1. **最小化修改**：只修复确认的问题，不添加冗余组件
2. **向后兼容**：确保不破坏现有功能
3. **验证驱动**：每个修改都有明确的验证标准

---

### 修复 1: 补全 Evidence Artifact 返回值 ⭐⭐⭐ (高优先级)

**必要性**：✅ 代码已创建 artifact，但 assembler 无法识别，导致机制失效

**合理性**：✅ 只需补全返回值，无需重构

**兼容性**：✅ 向后兼容（添加新字段不影响旧逻辑）

**实施**：

```python
# 文件: src/game_agent/aci/query.py
# 位置: _code_file_read() 方法，约 line 299

def _code_file_read(self, args: dict[str, Any]) -> dict[str, Any]:
    # ... 现有代码 ...
    
    # Persist full file content to evidence artifact
    evidence_id = EvidenceLedger.id_for(...)
    artifact_relative = ""
    if self.artifact_root:
        artifact_dir = self.artifact_root / "evidence-artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_file = artifact_dir / f"{evidence_id.replace(':', '_')}.txt"
        full_content = "\n".join(lines)
        artifact_file.write_text(full_content, encoding="utf-8")
        artifact_relative = artifact_file.relative_to(self.artifact_root).as_posix()
    
    self._map([node.id])
    payload = {
        "status": "ok",
        "node": _summary(node),
        "path": relative,
        "sha256": sha256,
        "start_line": start,
        "end_line": end,
        "total_lines": len(lines),
        "content": content[:maximum],
        # ✅ 添加这两个字段
        "evidence_artifact_path": artifact_relative if artifact_relative else None,
        "evidence_artifact_sha256": sha256,
    }
    
    return self._ok(
        "code_file_read",
        payload,
        ids=[node.id],
        sources=[f"graph:{node.id}", relative, f"source:{relative}:{start}-{end}"],
        status="source_verified",
        claim=f"Read source file {relative} at SHA-256 {sha256}.",
        # ✅ 添加这两个参数传递给 _ok()
        artifact_path=artifact_relative if artifact_relative else None,
        artifact_sha256=sha256,
    )
```

**验证标准**：
- 运行后 evidence items 应该包含 `artifact_path` 字段
- `project-context-state.json` 中 evidence 应该有 artifact 引用
- Mutation 时应该能从 artifact 读取内容

---

### 修复 2: 优化 Candidate Details 大小 ⭐⭐⭐ (高优先级)

**必要性**：✅ 当前 `detail_char_limit: 800` 对嵌套 JSON 无效

**合理性**：✅ 添加智能截断逻辑，保留关键信息

**兼容性**：✅ 不改变接口，只优化内部处理

**实施**：

```python
# 文件: src/game_agent/context/assembler.py
# 位置: _candidate_details() 方法，约 line 500-520

def _candidate_details(self) -> list[dict[str, Any]]:
    candidates = sorted(
        self.working_set.entries.values(),
        key=lambda entry: (entry.status != "relevant", -entry.relevance),
        reverse=True,
    )
    details: list[dict[str, Any]] = []
    for entry in candidates[: self.config.max_candidate_details]:
        if self.project_store is not None:
            detail = self.project_store.materialize(self.task_id, entry.node_id)
        else:
            hit = entry.detail is not None
            self.working_set.record_access(entry.node_id, hit=hit)
            detail = entry.detail
        if detail is None:
            detail = {
                "id": entry.node_id,
                "kind": entry.kind,
                "name": entry.name,
                "path": entry.path,
                "status": entry.status,
                "stale_reason": entry.stale_reason,
            }
        
        # ✅ 添加智能截断逻辑
        detail = self._smart_truncate_detail(detail, self.config.detail_char_limit)
        details.append(detail)
    return details

def _smart_truncate_detail(self, detail: dict[str, Any], char_limit: int) -> dict[str, Any]:
    """智能截断 detail，优先保留结构信息"""
    # 如果 detail 包含 'content' 字段（完整文件内容），优先截断它
    if "content" in detail and isinstance(detail["content"], str):
        content_len = len(detail["content"])
        # 为其他字段预留 200 字符
        content_limit = max(100, char_limit - 200)
        if content_len > content_limit:
            detail = dict(detail)  # 浅拷贝
            detail["content"] = detail["content"][:content_limit] + f"\n... (truncated {content_len - content_limit} chars)"
            detail["content_truncated"] = True
    
    # 如果仍然超过限制，使用现有的 _bounded_json
    return _bounded_json(detail, char_limit)
```

**验证标准**：
- Candidate details 的序列化长度不应超过 `detail_char_limit`
- 应该优先保留 node metadata，截断 content
- Token 增长速度应该减缓

---

### 修复 3: 回退上下文配置到合理值 ⭐⭐⭐ (高优先级)

**必要性**：✅ 当前配置过于激进，导致频繁压缩和状态丢失

**合理性**：✅ 基于原始 kitchen_chaos.json 的经验值

**兼容性**：✅ 只是配置调整，不改变代码逻辑

**实施**：

```json
// 文件: configs/ablation/group1-full.json
// 修改 context 部分

"context": {
    "enabled": true,
    "graph_path": "...",
    "state_path": "project-context-state.json",
    "auto_locate": true,
    "retrieval_strategy": "role_mmr",
    "max_test_candidates": 1,
    "retrieval_mmr_lambda": 0.82,
    
    // ✅ 调整这些参数
    "max_working_set_entries": 12,     // 从 4 改到 12
    "max_candidate_details": 3,        // 从 1 改到 3
    "max_recent_tool_results": 2,      // 从 1 改到 2
    "max_recent_messages": 3,          // 从 1 改到 3
    "detail_char_limit": 1200,         // 从 800 改到 1200
    "tool_summary_char_limit": 800,    // 从 600 改到 800
    "compression_trigger_ratio": 0.65, // 从 0.55 改到 0.65
    "working_set_detail_keep": 4,      // 从 2 改到 4
    "max_evidence_items": 12,          // 从 4 改到 12
    
    "max_memory_items_per_field": 12,
    "max_durable_instruction_chars": 4000
}
```

**验证标准**：
- Token 增长曲线应该更平缓
- Working set 不应在运行结束时为空
- 压缩触发频率降低

---

### 修复 4: 优化 Tool Results 序列化 ⭐⭐ (中优先级)

**必要性**：⚠️ 需要先验证 tool results 是否真的过大

**合理性**：✅ 如果过大，可以截断非关键字段

**兼容性**：✅ 不改变工具执行逻辑，只优化序列化

**实施**：

```python
# 文件: src/game_agent/context/models.py
# 位置: ToolObservation 类的 to_dict() 方法

class ToolObservation:
    # ... 现有字段 ...
    
    def to_dict(self, *, max_output_chars: int = 0) -> dict[str, Any]:
        """序列化为字典，可选截断输出"""
        result = {
            "tool": self.tool,
            "arguments": self.arguments,
            "output": self.output,
            "returncode": self.returncode,
            "exception_info": self.exception_info,
            "artifact_ref": self.artifact_ref,
            "timestamp": self.timestamp,
        }
        
        # ✅ 如果设置了限制且输出过大，进行截断
        if max_output_chars > 0 and isinstance(result["output"], str):
            output_len = len(result["output"])
            if output_len > max_output_chars:
                result["output"] = (
                    result["output"][:max_output_chars] 
                    + f"\n... (truncated {output_len - max_output_chars} chars, "
                    + f"full output in {self.artifact_ref})"
                )
        
        return result
```

```python
# 文件: src/game_agent/context/assembler.py
# 位置: _render_view() 方法，约 line 635

def _render_view(...) -> str:
    # ...
    # ✅ 使用截断限制
    recent_tools = [
        item.to_dict(max_output_chars=self.config.tool_summary_char_limit)
        for item in self.recent_tools[-self.config.max_recent_tool_results :]
    ]
    # ...
```

**验证标准**：
- Recent tool results 不应包含超过 `tool_summary_char_limit` 的输出
- 应该提示完整输出在 artifact 中
- Token 占用应该减少

---

### 修复 5: 添加 Evidence Artifact 回读提示 ⭐ (低优先级)

**必要性**：⚠️ 模型可能不知道可以从 artifact 回读

**合理性**：✅ 只需在 system prompt 中添加说明

**兼容性**：✅ 不改变代码逻辑

**实施**：

```python
# 文件: src/game_agent/context/assembler.py
# 位置: _render_view() 方法，约 line 672

def _render_view(...) -> str:
    # ...
    evidence_note = ""
    if verified or active:
        artifact_count = sum(1 for e in verified + active if e.get("artifact_path"))
        if artifact_count > 0:
            evidence_note = (
                f"\n\nNote: {artifact_count} evidence item(s) have full content "
                f"persisted in artifacts. If you need complete source during mutation, "
                f"reference the evidence ID and the system will retrieve the artifact."
            )
    
    return (
        workflow_capsule
        + "<virtual-project-context>\n"
        "This is a task-scoped view over durable project knowledge. "
        "Graph suggestions are not verified facts. "
        "Use artifact_ref to reopen an externalized raw result only when necessary."
        + evidence_note  # ✅ 添加提示
        + "\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n</virtual-project-context>"
    )
```

**验证标准**：
- 模型在 mutation 时应该能引用 evidence artifacts
- Mutation 成功率应该提升

---

## 第三部分：NOT 修复（避免冗余）

### 不修复 1: "永久控制胶囊"

**原因**：
- 从 `assembler.py:636-668` 看到，`workflow_capsule` **已经存在**：
  ```python
  workflow_capsule = ""
  if isinstance(workflow, dict) and workflow:
      workflow_capsule = (
          "<workflow-state>\n"
          "This controller-owned state is durable and overrides stale conversational plans.\n"
          + json.dumps(workflow, ensure_ascii=False, indent=2)
          + "\n</workflow-state>\n"
      )
  ```

**结论**：✅ **已实现**，无需添加。

---

### 不修复 2: "Message 历史清理"

**原因**：
- 从 `default.py:404-441` 确认，Agent **已经**使用 assembled messages
- `self.messages` 保留是为了 trajectory 审计，不会发送给模型

**结论**：✅ **不是问题**，无需修复。

---

### 不修复 3: "渐进式代码阅读"

**原因**：
- 从 `query.py:275-280` 看到，**已经支持**行范围读取：
  ```python
  start = max(1, int(args.get("start_line", 1)))
  end = min(len(lines), int(args.get("end_line", start + 199)))
  content = "\n".join(lines[start - 1:end])
  ```
- 配合 artifact 机制，已经实现了"预览 + 完整内容分离"

**结论**：✅ **已实现**，无需重复。

---

## 第四部分：实施计划

### Phase 1: 关键修复（本周）

1. ✅ **修复 1**: 补全 Evidence Artifact 返回值
   - 文件: `src/game_agent/aci/query.py`
   - 预计时间: 30 分钟
   - 风险: 低

2. ✅ **修复 3**: 回退上下文配置
   - 文件: `configs/ablation/group1-full.json`
   - 预计时间: 10 分钟
   - 风险: 无

### Phase 2: 优化（下周）

3. ✅ **修复 2**: 优化 Candidate Details 大小
   - 文件: `src/game_agent/context/assembler.py`
   - 预计时间: 1 小时
   - 风险: 低

4. ⚠️ **修复 4**: 优化 Tool Results 序列化（如果需要）
   - 文件: `src/game_agent/context/models.py`, `assembler.py`
   - 预计时间: 1 小时
   - 风险: 低
   - 前提: 先验证 tool results 是否真的过大

### Phase 3: 增强（可选）

5. ⚠️ **修复 5**: 添加 Evidence Artifact 回读提示
   - 文件: `src/game_agent/context/assembler.py`
   - 预计时间: 15 分钟
   - 风险: 无

---

## 第五部分：验证计划

### 验证 1: 单元测试

创建测试验证 artifact 机制：

```python
# tests/test_evidence_artifact.py
def test_code_file_read_creates_artifact():
    """验证 code_file_read 创建 artifact 并返回正确字段"""
    executor = StructuredQueryExecutor(...)
    result = executor.execute({
        "tool": "code_file_read",
        "arguments": {"path": "Assets/Scripts/Test.cs"}
    })
    
    assert result["output"]["evidence_artifact_path"] is not None
    assert result["output"]["evidence_artifact_sha256"] is not None
    assert Path(artifact_root / result["output"]["evidence_artifact_path"]).exists()
```

### 验证 2: E2E 测试

使用修复后的配置运行 5 次 baseline：

```powershell
for ($i=1; $i -le 5; $i++) {
    $runId = "fixed-baseline-run$i-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    game-agent-baseline --config configs/kitchen_chaos_fixed.json --run-id $runId
}
```

**成功标准**：
- Evidence artifacts 创建率 > 80%
- Token 增长速度 < 2,500 tokens/round
- FormatError 率 < 20%
- Working set 在运行结束时不为空

### 验证 3: Token 分析

对比修复前后的 token 分布：

```python
# scripts/analyze_token_distribution.py
def analyze_run(run_id):
    events = load_events(run_id)
    rounds = [e for e in events if e["event"] == "context_assembled"]
    
    for r in rounds:
        print(f"Round {r['round']}: "
              f"raw={r['raw_input_tokens']}, "
              f"working_set={r['working_set_metrics']['working_set_size']}, "
              f"compression={r['compression_reasons']}")
```

---

## 第六部分：预期效果

### Token 节省估算

| 修复 | 预期节省 | 理由 |
|------|---------|------|
| 修复 1 (Artifact 返回值) | 20-30% | 避免重复读取完整文件 |
| 修复 2 (Detail 截断) | 10-15% | 减少每个 candidate 的 token 占用 |
| 修复 3 (配置回退) | 5-10% | 减少压缩导致的重复搜索 |
| 修复 4 (Tool results) | 5-10% | 如果 tool outputs 确实过大 |
| **总计** | **40-65%** | 累积效果 |

### 成功率提升估算

| 指标 | 修复前 | 修复后（预期） |
|------|-------|---------------|
| FormatError 率 | 33% (1/3) | < 20% |
| Mutation 成功率 | 未知 | > 70% |
| 完成率 | 0% (0/3) | > 50% |

---

## 第七部分：风险评估

### 风险 1: 配置回退可能不够

**概率**: 30%

**影响**: 中

**缓解**: 如果仍然有 token 问题，进一步调整为：
```json
"max_working_set_entries": 16,
"max_candidate_details": 4,
"max_evidence_items": 16
```

### 风险 2: Artifact 机制可能有其他问题

**概率**: 20%

**影响**: 高

**缓解**: 添加详细日志，追踪 artifact 的创建和使用

### 风险 3: 模型仍然产生 FormatError

**概率**: 40%

**影响**: 高

**缓解**: 
1. 增加 `max_consecutive_format_errors` 到 5
2. 在 diagnosis 工具的 description 中添加更明确的格式示例
3. 考虑使用 structured output 强制格式

---

## 总结

### 需要修复的问题（5 个）

1. ✅ Evidence artifact 返回值缺失 - **高优先级**
2. ✅ Candidate details 过大 - **高优先级**
3. ✅ 上下文配置太激进 - **高优先级**
4. ⚠️ Tool results 可能过大 - **中优先级**（需先验证）
5. ⚠️ Artifact 回读提示缺失 - **低优先级**

### 不需要修复的问题（3 个）

1. ❌ Agent 使用原始 messages - **已正确实现**
2. ❌ 永久控制胶囊缺失 - **已存在**
3. ❌ 渐进式代码阅读缺失 - **已实现**

### 核心原则

**最小化修改，最大化效果**：
- 只修复确认的问题
- 不添加冗余组件
- 确保向后兼容
- 验证驱动开发

---

**文档版本**: 1.0  
**创建时间**: 2026-08-01  
**状态**: Ready for Implementation
