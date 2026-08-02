# State-event baseline report

- Run: `ablation-group3-run5-20260802-130538`
- Experiment valid: `True`
- Agent exit: `Submitted`
- Verified success: `True`
- Public validation: `True`
- Hidden validation: `True`
- Source unchanged: `True`

## Metrics

- Total tokens: `41944`
- Model calls: `5`
- Tool calls: `7`
- Navigation precision: `0.1667`
- Relevant recall: `0.6667`
- Repeated observation ratio: `0.0000`

## Recommended innovation

- `unity_project_graph`: 相关文件导航精度低，优先用 Scene/Component/C# 依赖图约束检索范围。
