# State-event baseline report

- Run: `ablation-group6-run4-20260802-135344`
- Experiment valid: `True`
- Agent exit: `RepeatedFormatError`
- Verified success: `False`
- Public validation: `True`
- Hidden validation: `False`
- Source unchanged: `True`

## Metrics

- Total tokens: `17796`
- Model calls: `2`
- Tool calls: `4`
- Navigation precision: `0.0000`
- Relevant recall: `0.0000`
- Repeated observation ratio: `0.0036`

## Recommended innovation

- `unity_project_graph`: 相关文件导航精度低，优先用 Scene/Component/C# 依赖图约束检索范围。
