# 多样化图检索离线 Pilot

日期：2026-07-31

## 设计

固定使用同一份 Kitchen Chaos 完整项目图、同一查询和同一 gold root-cause，不调用模型。评估六个可复现的缺陷注入规格：

1. 脚本状态事件订阅缺失；
2. Prefab SerializedProperty 指向错误；
3. Stove visual Component 缺失；
4. Scene UnityEvent listener 缺失；
5. Plates visual Component 缺失；
6. Delivery result 事件订阅缺失。

缺陷 manifest 位于 `configs/localization.pilot-defects.json`。完整机器可读结果位于
`artifacts/research/localization-diversity-pilot-20260731.json`。

消融条件：

- D0：纯相关性节点 Top-K；
- D1：按规范化 path 折叠；
- D2：path 折叠 + 测试候选配额；
- D3：path 折叠 + implementation/test role + 测试配额 + role-aware MMR + 一跳因果覆盖奖励。

D3 使用 `lambda=0.82`，初始 Top-4 至少保留四个 implementation 候选（不足时取全部），测试文件最多一个。文件级结果保持相关性顺序；MMR 只改变初始图节点工作集。

## 结果

| 指标 | D0 | D1 | D2 | D3 |
|---|---:|---:|---:|---:|
| candidate distinct-path ratio@4 | 0.833 | 1.000 | 1.000 | 1.000 |
| root-cause Recall@4 | 0.667 | 0.667 | 0.667 | 1.000 |
| root-cause MRR | 0.328 | 0.343 | 0.343 | 0.597 |
| file Recall@4 | 0.889 | 0.889 | 0.889 | 0.889 |
| candidate test ratio@4 | 0.000 | 0.000 | 0.000 | 0.000 |

D3 相对 D0：

- distinct-path ratio@4：`+0.167`；
- root-cause Recall@4：`+0.333`，达到 pilot 预设的至少 25 个百分点提升；
- root-cause MRR：`+0.270`；
- file Recall@4 无退化。

状态事件现有任务的 D3 初始四条 distinct path 为：

1. `Assets/Scripts/GameInput.cs`
2. `Assets/Scripts/UI/GameStartCountdownUI.cs`
3. `Assets/Scripts/UI/OptionUI.cs`
4. `Assets/Scripts/KitchenGameManager.cs`

因此不再出现同一 PlayMode 测试文件占据三个槽位，且根因实现文件进入前四。

## 统计解释

六个任务上的方向一致但样本仍小。D3 相对 D0 的 root-cause Recall@4 配对置换检验
`p=0.5`，root-cause MRR `p=0.125`；Holm 校正后均不显著。本结果支持进入真实模型 pilot，
但不能单独作为总体显著性结论。后续应扩充缺陷与随机种子，而不是把这六个任务当作最终统计证据。

