# State-event baseline report

- Run: `ablation-group8-run3-20260802-142630`
- Experiment valid: `True`
- Agent exit: `TotalTokenLimitExceeded`
- Verified success: `False`
- Public validation: `True`
- Hidden validation: `False`
- Source unchanged: `True`

## Metrics

- Total tokens: `67493`
- Model calls: `7`
- Tool calls: `9`
- Navigation precision: `0.1667`
- Relevant recall: `0.6667`
- Repeated observation ratio: `0.0000`

## Recommended innovation

- `unity_project_graph`: 相关文件导航精度低，优先用 Scene/Component/C# 依赖图约束检索范围。
