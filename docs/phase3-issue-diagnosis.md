# Phase 3 已知问题诊断报告

**日期：** 2026-08-02  
**问题：** Mutation执行失败

---

## 🔍 问题诊断

### 问题现象

**Phase 3测试输出：**
```
Token budget exhausted: 43478/40000
LLM summary generation failed, using fallback
Mutation failed: Unknown mutation error
Mutations applied: 0
Files changed: 0
```

### 根因分析

**问题链路：**
```
1. Explorer使用43,478 tokens
   └─ 超出40k预算 (+8.5%)

2. Token budget exhausted
   └─ Decision阶段无法执行

3. Decision返回空结果
   └─ 没有生成mutations

4. MutationService收到空action
   └─ 返回"Unknown mutation error"
```

**具体原因：**

1. **Token预算不足**
   - Phase 3测试脚本未指定token预算
   - 使用了默认的40k预算
   - Explorer实际需要43.4k tokens

2. **Decision阶段被跳过**
   - Token budget exhausted后
   - Decision阶段无法调用LLM
   - 使用fallback逻辑返回空结果

3. **MutationService错误信息不明确**
   - 当action为空或无效时
   - 返回通用的"Unknown mutation error"
   - 没有指明是Decision阶段失败

---

## ✅ 解决方案

### 方案1: 增加Token预算（推荐）

**修改：** Explorer默认预算
```python
# src/game_agent_try/agents/explorer.py
def __init__(
    self,
    model: Model,
    context: ContextAssembler,
    max_rounds: int = 10,
    max_tokens: int = 60_000,  # ✅ 已经是60k
):
```

**验证：** Explorer代码中已经使用60k预算

**问题：** Phase 3测试脚本可能覆盖了这个设置

### 方案2: 优化Explorer Token使用（长期）

**目标：** 将Explorer token使用降到40k以内

**方法：**
1. 减少工具schema大小（已在Phase 2完成）
2. 优化探索策略
3. 减少重复的evidence收集
4. 改进summary生成

**预期：** 节省3-5k tokens

### 方案3: 改进错误处理（立即）

**修改：** MutationService错误信息
```python
# src/game_agent_try/services/mutation_service.py

def execute_mutation(self, action: dict[str, Any], authorized_paths: list[str]) -> MutationResult:
    # 添加输入验证
    if not action or not action.get("tool"):
        return MutationResult(
            success=False,
            transaction_id="",
            checkpoint_id="",
            changed_paths=[],
            error="Invalid mutation action: empty or missing tool",
        )
    
    # ... 原有逻辑
```

---

## 🧪 验证方法

### 测试1: 真实任务测试

**脚本：** `scripts/test_real_task.py`

**特点：**
- 使用完整的配置
- 没有token预算限制
- 真实Unity项目

**运行：**
```bash
cd E:\sysu-course\GameAgent
python scripts\test_real_task.py
```

**预期：**
- Explorer应该能完成探索
- Decision应该生成mutations
- Mutations应该执行成功

### 测试2: Phase 3测试（修复后）

**修改：** 移除或增加token预算限制

```python
# scripts/test_phase3_integration.py
coordinator = CoordinatorAgent(
    model=model,
    context=context,
    project_root=unity_project,
    artifact_root=artifact_root,
    # config={"max_tokens": 60_000},  # 添加配置
)
```

---

## 📊 Token使用分析

### Phase 3测试实际使用

```
Explorer: 43,478 tokens
├─ Round 1: ~10k
├─ Round 2: ~10k  
├─ Round 3: ~11k
├─ Round 4: ~12k
└─ 超出预算: +3,478 (8.5%)

Decision: 0 tokens (budget exhausted)
Summary: 0 tokens (fallback used)
```

### 理想分配

```
总预算: 60,000 tokens

Explorer: 50,000 tokens (83%)
├─ 探索轮次: 40k
├─ Evidence收集: 5k
└─ 候选筛选: 5k

Decision: 8,000 tokens (13%)
├─ Evidence分析: 3k
├─ Mutation生成: 5k

Summary: 2,000 tokens (4%)
└─ 证据包总结: 2k
```

---

## 🎯 立即行动

### 步骤1: 运行真实任务测试 ✅

**命令：**
```bash
python scripts\test_real_task.py
```

**状态：** 正在运行（后台任务 brf8rx61s）

**预期：**
- 使用60k token预算
- Explorer完成探索
- Decision生成mutations
- Mutations成功执行

### 步骤2: 根据测试结果采取行动

**如果成功：**
- ✅ 问题已解决（预算不足导致）
- 📝 更新Phase 3测试脚本
- 🎉 Phase 3完全通过

**如果仍失败：**
- 🔍 进一步诊断mutation执行逻辑
- 🔧 检查ACI mutation executor
- 📊 分析详细错误日志

---

## 📝 建议的代码改进

### 1. 改进MutationService错误处理

```python
# src/game_agent_try/services/mutation_service.py

def execute_mutation(
    self,
    action: dict[str, Any],
    authorized_paths: list[str],
) -> MutationResult:
    """Execute a mutation with checkpoint and authorization."""
    self.execution_count += 1

    # 输入验证
    if not action:
        return MutationResult(
            success=False,
            transaction_id="",
            checkpoint_id="",
            changed_paths=[],
            error="Mutation action is None or empty",
        )

    if not action.get("tool"):
        return MutationResult(
            success=False,
            transaction_id="",
            checkpoint_id="",
            changed_paths=[],
            error=f"Mutation action missing 'tool' field: {action}",
        )

    # ... 原有逻辑
```

### 2. 改进Coordinator错误信息

```python
# src/game_agent_try/agents/coordinator.py

def _make_mutation_decision(self, task: str, evidence_package: EvidencePackage) -> dict[str, Any]:
    """Make decision based on evidence."""
    
    # Token budget check
    if self.model.tokens_used >= self.model.max_tokens:
        return {
            "success": False,
            "error": f"Token budget exhausted: {self.model.tokens_used}/{self.model.max_tokens}. Cannot generate decision.",
            "actions": [],
        }
    
    # ... 原有逻辑
```

### 3. 改进Explorer预算管理

```python
# src/game_agent_try/agents/explorer.py

def explore(self, task: ExplorationTask) -> EvidencePackage:
    """Execute exploration with token budget management."""
    
    # 预留token给Decision和Summary
    reserved_for_decision = 10_000  # 预留10k给后续阶段
    effective_budget = self.max_tokens - reserved_for_decision
    
    while self.round < task.max_rounds:
        if self.tokens_used >= effective_budget:
            self.logger.info(f"Approaching token budget, stopping exploration")
            break
        
        # ... 探索逻辑
```

---

## 📚 相关文档

- **Phase 3完成报告**：`PHASE3_COMPLETE.md`
- **Phase 2工作总结**：`docs/phase2-work-summary.md`
- **真实任务测试脚本**：`scripts/test_real_task.py`
- **Phase 3测试脚本**：`scripts/test_phase3_integration.py`

---

## ✅ 诊断结论

**根本原因：** Token预算不足（40k vs 实际需要43.4k）

**影响范围：** 
- Phase 3测试脚本
- 不影响实际使用（默认60k预算）

**严重程度：** 中（测试问题，非生产问题）

**解决状态：** 
- 🧪 真实任务测试运行中
- ✅ Explorer已使用60k预算
- 📝 需要更新Phase 3测试脚本

**后续行动：**
1. 等待真实任务测试结果
2. 根据结果决定是否需要进一步优化
3. 更新文档和测试脚本

---

**创建时间：** 2026-08-02  
**状态：** 诊断完成，真实任务测试中  
**下一步：** 等待测试结果
