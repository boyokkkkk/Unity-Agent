# Token 效率问题完整修复总结

## 执行时间
2026-08-01

## 核心发现

经过深入代码审查和数据分析，发现：

### ❌ 错误假设
- ~~"Evidence Artifact 机制未实现"~~ → **已完全实现**
- ~~"Context Assembly 使用原始 messages"~~ → **已正确使用 assembled messages**
- ~~"Compression 是假的"~~ → **Compression 真实有效**

### ✅ 真正问题
**原始配置过于激进，导致恶性循环**

```
配置太小 → 频繁压缩 → 信息丢失 → 重复搜索 → Token 增长
```

---

## 根本原因

### 问题配置对比

| 参数 | 原值 | 问题 | 优化值 |
|------|------|------|--------|
| max_working_set_entries | 4 | 只能保留 4 个候选 | 12 |
| max_candidate_details | 1 | 每轮只能看 1 个详情 | 3 |
| max_recent_messages | 1 | 几乎无对话历史 | 3 |
| max_evidence_items | 4 | Evidence 快速淘汰 | 12 |
| compression_trigger_ratio | 0.55 | 过早触发压缩 | 0.65 |
| working_set_detail_keep | 2 | 压缩时保留太少 | 4 |
| max_consecutive_format_errors | 3 | 容错不足 | 5 |

### Token 增长路径

**原配置的恶性循环**：

```
Round 1: 加载初始候选 (4 个) → 873 tokens
Round 2: 读取 1 个详情，添加 evidence → 3,878 tokens (+3,005)
Round 3: 触发压缩 (55% 阈值)，丢弃旧 evidence → 7,823 tokens (+3,945)
Round 4: 模型忘记之前的内容，重新搜索 → 10,199 tokens (+2,376)
Round 5: 继续添加新候选和 evidence → 12,747 tokens (+2,548)
Round 6: 再次压缩，FormatError 开始出现 → 16,223 tokens (+3,476)
Round 7-8: 多次 FormatError，任务失败
```

**核心问题**：
1. 只能保留 4 个 evidence → 诊断时引用的 evidence 可能已被压缩 → FormatError
2. 只能看 1 个候选详情 → 信息不足，需要多轮查看
3. 压缩触发太早 (55%) → 过早丢失有用信息

---

## 解决方案

### 修复：调整配置参数

**文件**: `configs/kitchen_chaos_optimized.json`

**关键改动**：
- `max_working_set_entries`: 4 → **12** (+200%)
- `max_candidate_details`: 1 → **3** (+200%)
- `max_recent_messages`: 1 → **3** (+200%)
- `max_evidence_items`: 4 → **12** (+200%)
- `compression_trigger_ratio`: 0.55 → **0.65** (+18%)
- `working_set_detail_keep`: 2 → **4** (+100%)
- `max_consecutive_format_errors`: 3 → **5** (+67%)

**理由**：
1. **更大的缓冲区** → 减少压缩频率
2. **更多的 evidence 保留** → 避免诊断时引用失效
3. **更多的候选详情** → 减少重复查看
4. **更高的容错** → 给模型更多机会

---

## 验证计划

### 自动化验证脚本

已创建 `scripts/verify_optimized_config.ps1`：
- 运行 3-5 次优化配置测试
- 自动分析 token 增长、FormatError 率、成功率
- 与原配置对比

### 运行方式

```powershell
cd E:\sysu-course\GameAgent
.\scripts\verify_optimized_config.ps1 -RunCount 3
```

### 成功标准

| 指标 | 原配置 | 目标 |
|------|--------|------|
| Token 增长速度 | ~3,000/round | < 2,000/round |
| FormatError 率 | 33% | < 20% |
| 任务完成率 | 0% | > 50% |
| Working set 最终大小 | 0 | > 4 |

---

## 关键洞察

### 为何创新点"失效"？

**创新点本身都正常工作**：
- ✅ Evidence Artifact: 代码完整，正常创建
- ✅ Dynamic Tool Exposure: 正确暴露工具
- ✅ Context Compression: 真实压缩（只发送 2 条 assembled messages）
- ✅ Workflow Control: 状态机正常运行

**问题在于配置太小**：
- 就像给汽车只装 1 升油
- 汽车本身（引擎、变速箱）都很好
- 但油太少，频繁熄火，需要反复加油
- **总油耗反而更高**

### 教训

1. **配置参数需要基于实验，不是直觉**
2. **Token 节省靠机制（artifact、compression），不靠限制（小配置）**
3. **过小的配置导致恶性循环**
4. **诊断需要完整的证据链**

---

## 不需要的修复

以下修复**不必要**，因为已经实现：

### ❌ 修复 1: 补全 Evidence Artifact 返回值
**原因**: 代码已完整实现（`query.py:309, 318-319`）

### ❌ 修复 2: 修改 Agent 使用 assembled messages
**原因**: Agent 已正确使用（`default.py:404-441`）

### ❌ 修复 3: 实现永久控制胶囊
**原因**: 已存在 workflow_capsule（`assembler.py:662-668`）

### ❌ 修复 4: 实现渐进式代码阅读
**原因**: 已支持行范围读取 + artifact 分离（`query.py:275-296`）

---

## 实施状态

### ✅ 已完成
1. 深入代码审查，确认真正问题
2. 创建优化配置文件 `kitchen_chaos_optimized.json`
3. 创建验证脚本 `verify_optimized_config.ps1`
4. 编写完整诊断报告

### ⏳ 待完成
1. 运行验证测试（3-5 次）
2. 分析结果，确认改善
3. 如果成功，更新所有配置文件
4. 如果仍有问题，考虑可选优化（智能截断）

---

## 预期效果

### Token 节省
- **机制**: 更大的缓冲区 → 减少重复搜索
- **估算**: Token 增长速度降低 30-40%
- **从**: ~3,000 tokens/round
- **到**: ~1,800-2,100 tokens/round

### 成功率提升
- **机制**: 更多 evidence 保留 → 减少 FormatError
- **估算**: FormatError 率从 33% 降到 < 20%
- **估算**: 任务完成率从 0% 提升到 > 50%

### 质量提升
- **机制**: 更多上下文 → 更好的决策
- **效果**: 更准确的诊断，更少的重复操作

---

## 后续行动

### 立即（今天）
1. ⏳ 运行验证脚本，获取实际数据
2. ⏳ 对比分析，确认改善

### 短期（本周）
3. ⏳ 如果验证成功，更新所有配置
4. ⏳ 更新文档和使用指南

### 中期（下周）
5. ⏳ 进行配置参数消融实验
6. ⏳ 建立配置推荐指南
7. ⏳ 考虑可选优化（如智能截断）

---

## 结论

### 核心问题
**不是创新点失效，而是配置太激进**

### 解决方案
**简单：调整配置到合理值**

### 修复类型
**配置优化，无需代码修改**

### 信心度
**高 - 基于充分的代码审查和数据分析**

---

**文档版本**: 1.0  
**创建时间**: 2026-08-01  
**下一步**: 运行验证测试
