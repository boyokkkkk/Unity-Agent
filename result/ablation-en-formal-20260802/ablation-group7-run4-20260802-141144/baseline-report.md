# State-event baseline report

- Run: `ablation-group7-run4-20260802-141144`
- Experiment valid: `True`
- Agent exit: `Submitted`
- Verified success: `True`
- Public validation: `True`
- Hidden validation: `True`
- Source unchanged: `True`

## Metrics

- Total tokens: `75080`
- Model calls: `9`
- Tool calls: `9`
- Navigation precision: `0.1667`
- Relevant recall: `0.6667`
- Repeated observation ratio: `0.0000`

## Recommended innovation

- `unity_project_graph`: 相关文件导航精度低，优先用 Scene/Component/C# 依赖图约束检索范围。
