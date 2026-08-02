# State-event baseline report

- Run: `ablation-group9-run3-20260802-144448`
- Experiment valid: `True`
- Agent exit: `TotalTokenLimitExceeded`
- Verified success: `False`
- Public validation: `True`
- Hidden validation: `False`
- Source unchanged: `True`

## Metrics

- Total tokens: `75732`
- Model calls: `9`
- Tool calls: `9`
- Navigation precision: `0.1667`
- Relevant recall: `0.6667`
- Repeated observation ratio: `0.0000`

## Recommended innovation

- `unity_project_graph`: 相关文件导航精度低，优先用 Scene/Component/C# 依赖图约束检索范围。
