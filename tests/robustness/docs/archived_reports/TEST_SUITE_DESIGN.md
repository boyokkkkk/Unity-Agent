# 鲁棒性测试任务集设计

**设计日期：** 2026-08-02  
**目标：** 验证系统在不同类型任务下的表现和鲁棒性

---

## 🎯 测试任务分类

### 维度1：任务复杂度
- **Simple** - 单文件、单点修改
- **Medium** - 单文件、多点修改或逻辑推理
- **Complex** - 多文件关联、需要深度探索
- **Very Complex** - 架构级修改、跨模块影响

### 维度2：问题类型
- **Bug Fix** - 修复明确的bug
- **Feature Addition** - 添加新功能
- **Refactoring** - 代码重构
- **Performance** - 性能优化
- **UI/UX** - 界面和交互

### 维度3：信息明确度
- **Precise** - 问题描述精确，给出文件和位置
- **Vague** - 只描述现象，需要自行定位
- **Misleading** - 包含误导性信息

---

## 📋 测试任务集（15个任务）

### Group A: Bug修复类（5个）

#### Task A1: Simple Bug - 明确定位
**类型：** Simple + Bug Fix + Precise  
**描述：**
```
在 Assets/Scripts/Player/Player.cs 的 HandleMovement() 方法中，
玩家移动速度计算有误，应该是 moveSpeed * Time.deltaTime * 2f，
但当前只有 moveSpeed * Time.deltaTime。
请修复这个系数错误。
```

**期望行为：**
- 快速识别为Simple任务
- 直接读取指定文件
- 精确修改一行代码
- Token使用 < 5,000

**验证点：**
- [ ] 复杂度评估正确（Simple）
- [ ] 文件定位准确
- [ ] 修改最小化
- [ ] 执行时间 < 20秒

---

#### Task A2: Medium Bug - 需要推理
**类型：** Medium + Bug Fix + Vague  
**描述：**
```
玩家按下暂停键后，游戏暂停了，但音乐还在播放。
应该暂停时音乐也停止，恢复时音乐继续。
目前暂停功能位于 KitchenGameManager 中。
```

**期望行为：**
- 评估为Medium或Complex
- 探索KitchenGameManager和音乐相关代码
- 找到AudioManager或类似组件
- 添加音乐暂停/恢复调用

**验证点：**
- [ ] 找到相关的音乐管理代码
- [ ] 正确添加暂停/恢复逻辑
- [ ] Token使用 10,000-30,000
- [ ] 执行时间 30-60秒

---

#### Task A3: Complex Bug - 状态同步
**类型：** Complex + Bug Fix + Vague  
**描述：**
```
在多人游戏模式下，当玩家1拾取食材后，玩家2的屏幕上
该食材仍然显示在原位置。这是一个网络同步问题。
请定位并修复这个状态同步bug。
```

**期望行为：**
- 评估为Complex
- 探索网络同步代码、食材管理、UI更新
- 识别状态同步机制
- 添加网络事件或状态广播

**验证点：**
- [ ] 找到网络同步相关代码
- [ ] 识别状态广播机制
- [ ] 正确添加同步逻辑
- [ ] Token使用 30,000-60,000

---

#### Task A4: Bug修复 - 误导性信息
**类型：** Medium + Bug Fix + Misleading  
**描述：**
```
玩家报告说计时器有问题，时间走得太快了。
我怀疑是 CountdownTimer.cs 的 Update() 方法中
Time.deltaTime 被乘了两次导致的。
请检查并修复。

注：实际问题可能不在CountdownTimer，而在GameManager的timeScale设置
```

**期望行为：**
- 不被误导，探索多个可能的位置
- 检查CountdownTimer和GameManager
- 发现真正的问题（timeScale设置错误）

**验证点：**
- [ ] 没有被误导到错误的文件
- [ ] 找到真正的问题根源
- [ ] 正确修复

---

#### Task A5: Null Reference Bug
**类型：** Medium + Bug Fix + Vague  
**描述：**
```
游戏运行时控制台报错：
NullReferenceException: Object reference not set to an instance of an object
at DeliveryManager.SpawnNewRecipe()

请找到并修复这个空引用问题。
```

**期望行为：**
- 读取DeliveryManager代码
- 识别可能为null的对象
- 添加null检查或初始化

**验证点：**
- [ ] 找到空引用的具体位置
- [ ] 添加适当的null检查
- [ ] 不过度防御（只在必要处添加检查）

---

### Group B: 功能添加类（5个）

#### Task B1: Simple Feature - 添加常量
**类型：** Simple + Feature + Precise  
**描述：**
```
在 Assets/Scripts/Player/Player.cs 中添加一个公共常量：
public const float MAX_INTERACTION_DISTANCE = 2f;

然后在 HandleInteractions() 方法中使用这个常量
替代硬编码的 2f 值。
```

**期望行为：**
- Simple任务
- 添加常量定义
- 替换硬编码值

**验证点：**
- [ ] 常量定义正确
- [ ] 硬编码值被替换
- [ ] 执行时间 < 20秒

---

#### Task B2: Medium Feature - 添加计数器
**类型：** Medium + Feature + Vague  
**描述：**
```
需要在UI上显示玩家成功交付的订单数量。
当前DeliveryManager负责处理订单交付，
但没有记录总数。请添加这个功能。
```

**期望行为：**
- 探索DeliveryManager和UI代码
- 添加计数变量
- 在交付成功时增加计数
- 触发UI更新事件

**验证点：**
- [ ] 添加了计数逻辑
- [ ] 正确触发UI更新
- [ ] 遵循现有的事件模式

---

#### Task B3: Complex Feature - 新的游戏机制
**类型：** Complex + Feature + Vague  
**描述：**
```
添加"连击"系统：玩家连续成功交付订单（中间间隔<5秒）
时获得连击加分。连击数显示在UI上，断连后重置。

需要：
1. 记录上次交付时间
2. 计算连击数
3. 应用分数加成
4. UI显示连击状态
```

**期望行为：**
- 评估为Complex
- 探索多个相关系统（交付、计分、UI）
- 设计状态管理
- 添加多处修改

**验证点：**
- [ ] 连击逻辑正确
- [ ] 分数加成计算准确
- [ ] UI正确显示
- [ ] 状态重置正确

---

#### Task B4: Feature - 配置化
**类型：** Medium + Feature + Precise  
**描述：**
```
将游戏难度相关的硬编码值提取到ScriptableObject配置中：
- 游戏时长
- 倒计时时长
- 订单生成间隔

创建 GameDifficultyConfig.cs 和相应的asset。
```

**期望行为：**
- 创建新的ScriptableObject类
- 提取硬编码值
- 修改使用这些值的地方

**验证点：**
- [ ] ScriptableObject定义正确
- [ ] 硬编码值被替换
- [ ] 引用配置对象
- [ ] 不引入breaking changes

---

#### Task B5: Feature - 音效系统
**类型：** Complex + Feature + Vague  
**描述：**
```
游戏缺少音效反馈。需要在以下操作时播放音效：
- 拾取食材
- 切菜
- 放置食材
- 交付订单成功/失败

请设计并实现音效系统。
```

**期望行为：**
- 设计音效管理器
- 在关键操作点添加音效调用
- 处理音效资源引用

**验证点：**
- [ ] 音效管理器设计合理
- [ ] 关键点正确触发音效
- [ ] 不阻塞主逻辑

---

### Group C: 重构类（3个）

#### Task C1: Simple Refactor - 提取方法
**类型：** Simple + Refactoring + Precise  
**描述：**
```
在 Player.cs 的 Update() 方法中，输入处理代码太长。
请将输入处理逻辑提取到单独的 HandleInput() 方法中。
```

**期望行为：**
- 提取方法
- 保持功能不变
- 清理Update()

**验证点：**
- [ ] 方法提取正确
- [ ] 功能保持一致
- [ ] 代码更清晰

---

#### Task C2: Medium Refactor - 魔法数字
**类型：** Medium + Refactoring + Vague  
**描述：**
```
代码中有很多魔法数字（hardcoded values），
特别是在 KitchenGameManager 和 DeliveryManager 中。
请找到并重构这些魔法数字为命名常量。
```

**期望行为：**
- 识别魔法数字
- 转换为有意义的常量
- 保持功能不变

**验证点：**
- [ ] 识别了主要魔法数字
- [ ] 常量命名清晰
- [ ] 功能保持一致

---

#### Task C3: Complex Refactor - 状态机模式
**类型：** Complex + Refactoring + Vague  
**描述：**
```
KitchenGameManager 中的状态管理使用了大量的 if-else。
建议重构为状态机模式，使代码更清晰和可扩展。

当前状态：WaitingToStart, CountdownToStart, GamePlaying, GameOver
```

**期望行为：**
- 分析当前状态逻辑
- 设计状态机架构
- 重构为状态模式
- 保持现有功能

**验证点：**
- [ ] 状态机设计合理
- [ ] 所有状态转换正确
- [ ] 功能完全保持
- [ ] 代码更可维护

---

### Group D: 边界情况（2个）

#### Task D1: 空项目测试
**类型：** N/A  
**描述：**
```
在一个空的Unity项目中添加基础的Player移动脚本。
```

**期望行为：**
- 识别为无法完成（缺少上下文）
- 或提示需要更多信息

**验证点：**
- [ ] 正确处理缺少上下文的情况
- [ ] 不产生幻觉代码

---

#### Task D2: 超出能力范围
**类型：** Very Complex  
**描述：**
```
重新设计整个游戏架构，将单人模式改为多人联机模式，
包括网络同步、服务器权威逻辑、延迟补偿等。
```

**期望行为：**
- 识别任务过于复杂
- 建议分解为多个子任务
- 或拒绝执行

**验证点：**
- [ ] 正确识别超出能力
- [ ] 给出合理的反馈

---

## 📊 测试矩阵

| 任务ID | 复杂度 | 类型 | 信息明确度 | 预期Token | 预期时间 | 优先级 |
|--------|--------|------|-----------|----------|----------|--------|
| A1 | Simple | Bug | Precise | <5k | <20s | P0 |
| A2 | Medium | Bug | Vague | 10-30k | 30-60s | P0 |
| A3 | Complex | Bug | Vague | 30-60k | 60-120s | P1 |
| A4 | Medium | Bug | Misleading | 15-40k | 40-90s | P1 |
| A5 | Medium | Bug | Vague | 10-30k | 30-60s | P0 |
| B1 | Simple | Feature | Precise | <5k | <20s | P0 |
| B2 | Medium | Feature | Vague | 10-30k | 30-60s | P0 |
| B3 | Complex | Feature | Vague | 40-70k | 60-120s | P1 |
| B4 | Medium | Feature | Precise | 15-35k | 30-70s | P1 |
| B5 | Complex | Feature | Vague | 40-70k | 60-120s | P2 |
| C1 | Simple | Refactor | Precise | <8k | <25s | P1 |
| C2 | Medium | Refactor | Vague | 15-40k | 40-90s | P1 |
| C3 | Complex | Refactor | Vague | 50-80k | 90-150s | P2 |
| D1 | N/A | Edge | N/A | ? | ? | P2 |
| D2 | Very Complex | Edge | Vague | ? | ? | P2 |

---

## 🎯 测试目标和成功标准

### 整体目标
- **通过率目标：** ≥80% (12/15任务)
- **Token效率：** 平均节省≥75%
- **执行时间：** 符合预期范围
- **代码质量：** 无breaking changes

### 评估维度

#### 1. 任务理解 (40%)
- [ ] 复杂度评估准确率 ≥90%
- [ ] 正确识别任务类型
- [ ] 理解任务意图

#### 2. 探索效率 (30%)
- [ ] 找到相关文件准确率 ≥85%
- [ ] Evidence收集充分性
- [ ] Token使用在预期范围内

#### 3. 解决方案质量 (20%)
- [ ] 修改正确性 100%
- [ ] 代码风格一致性
- [ ] 最小化修改原则

#### 4. 鲁棒性 (10%)
- [ ] 处理模糊任务
- [ ] 处理误导信息
- [ ] 边界情况处理

---

## 🔧 测试执行计划

### Phase 1: 基础验证（P0任务）
**任务：** A1, A2, A5, B1, B2  
**目标：** 验证基本功能和常见场景  
**预期完成率：** 100% (5/5)

### Phase 2: 进阶验证（P1任务）
**任务：** A3, A4, B4, C1, C2  
**目标：** 验证复杂场景和特殊情况  
**预期完成率：** ≥80% (4/5)

### Phase 3: 压力测试（P2任务）
**任务：** B3, B5, C3, D1, D2  
**目标：** 测试极限和边界  
**预期完成率：** ≥60% (3/5)

---

## 📝 执行脚本模板

```python
# scripts/run_robustness_tests.py

TEST_TASKS = {
    "A1": {
        "description": "...",
        "expected_complexity": "simple",
        "expected_files": ["Assets/Scripts/Player/Player.cs"],
        "success_criteria": {
            "files_changed": 1,
            "lines_changed": (1, 3),
            "token_budget": 5000,
        }
    },
    # ... 其他任务
}

def run_test(task_id):
    task = TEST_TASKS[task_id]
    result = coordinator.execute(task["description"])
    
    # 验证
    assert result.complexity == task["expected_complexity"]
    assert result.files_changed <= task["success_criteria"]["files_changed"]
    assert result.tokens < task["success_criteria"]["token_budget"]
    
    return result

# 批量执行
results = {tid: run_test(tid) for tid in PHASE1_TASKS}
```

---

## 📊 预期结果仪表板

```
╔═══════════════════════════════════════════════╗
║         鲁棒性测试结果摘要                    ║
╠═══════════════════════════════════════════════╣
║ 总任务数：           15                       ║
║ 通过任务：           12 (80%)                 ║
║ 失败任务：            3 (20%)                 ║
║ ─────────────────────────────────────────────║
║ 平均Token节省：      78%                      ║
║ 平均执行时间：       45秒                     ║
║ 复杂度评估准确率：   93%                      ║
║ ─────────────────────────────────────────────║
║ Simple任务通过率：   100% (3/3)               ║
║ Medium任务通过率：   85% (6/7)                ║
║ Complex任务通过率：  60% (3/5)                ║
╚═══════════════════════════════════════════════╝
```

---

**设计者：** Claude Code  
**设计时间：** 2026-08-02 18:10  
**版本：** v1.0  
**状态：** 待执行
