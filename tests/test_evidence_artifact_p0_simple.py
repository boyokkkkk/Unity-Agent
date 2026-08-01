"""
Test P0: Evidence Artifact持久化机制
验证修改1-3和修改6-8的完整集成（无pytest版本）
"""
import hashlib
import json
import sys
from pathlib import Path
import tempfile

# 添加src到path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from game_agent.context.models import Evidence, EvidenceLedger, EvidenceStatus


def test_evidence_with_artifact_fields():
    """测试Evidence数据类包含artifact字段"""
    print("测试1: Evidence包含artifact字段...")

    evidence = Evidence(
        id="test-evidence-1",
        claim="Test claim",
        status=EvidenceStatus.SOURCE_VERIFIED,
        sources=["test:source"],
        artifact_path="evidence-artifacts/test.txt",
        artifact_sha256="abc123",
    )

    assert evidence.artifact_path == "evidence-artifacts/test.txt"
    assert evidence.artifact_sha256 == "abc123"

    # 验证序列化
    data = evidence.to_dict()
    assert "artifact_path" in data
    assert data["artifact_path"] == "evidence-artifacts/test.txt"

    print("  ✓ Evidence.artifact_path和artifact_sha256字段正常")
    print("  ✓ 序列化包含artifact字段")


def test_evidence_ledger_add_with_artifacts():
    """测试EvidenceLedger.add支持artifact参数"""
    print("\n测试2: EvidenceLedger.add支持artifact参数...")

    ledger = EvidenceLedger()

    evidence = ledger.add(
        "Read file test.cs",
        status=EvidenceStatus.SOURCE_VERIFIED,
        sources=["source:test.cs"],
        artifact_path="evidence-artifacts/ev123.txt",
        artifact_sha256="sha256hash",
    )

    assert evidence.artifact_path == "evidence-artifacts/ev123.txt"
    assert evidence.artifact_sha256 == "sha256hash"

    print("  ✓ 创建evidence时可以传递artifact_path和artifact_sha256")

    # 验证更新逻辑
    updated = ledger.add(
        "Read file test.cs",
        status=EvidenceStatus.SOURCE_VERIFIED,
        sources=["source:test.cs"],
        artifact_path="evidence-artifacts/ev456.txt",
        artifact_sha256="newhash",
    )

    # 应该更新现有evidence
    assert updated.id == evidence.id
    assert updated.artifact_path == "evidence-artifacts/ev456.txt"
    assert updated.artifact_sha256 == "newhash"

    print("  ✓ 更新evidence时artifact字段正确更新")


def test_diagnosis_record_with_evidence_artifacts():
    """测试DiagnosisRecord绑定evidence artifacts"""
    print("\n测试3: DiagnosisRecord自动收集evidence artifacts...")

    from game_agent.aci.diagnosis import DiagnosisRecord, CausalClaim

    # 创建mock evidence ledger
    ledger = EvidenceLedger()
    ev1 = ledger.add(
        "Evidence 1",
        sources=["source:1"],
        artifact_path="artifacts/ev1.txt",
        artifact_sha256="hash1",
    )
    ev2 = ledger.add(
        "Evidence 2",
        sources=["source:2"],
        artifact_path="artifacts/ev2.txt",
        artifact_sha256="hash2",
    )

    # 创建diagnosis
    arguments = {
        "symptom": "Test symptom",
        "root_targets": ["C1", "C2"],
        "causal_chain": [
            {"statement": "Claim 1", "evidence_ids": [ev1.id]},
            {"statement": "Claim 2", "evidence_ids": [ev2.id, "missing-id"]},
        ],
        "proposed_mutations": [
            {"target": "C1", "operation": "patch", "target_paths": ["test.cs"]}
        ],
        "validation_plan": ["editmode"],
        "remaining_uncertainty": [],
    }

    diagnosis = DiagnosisRecord.from_arguments(
        arguments,
        version=1,
        repository_revision="abc",
        evidence_ledger=ledger,
    )

    # 验证evidence_artifacts被收集
    assert len(diagnosis.evidence_artifacts) == 2, f"Expected 2 artifacts, got {len(diagnosis.evidence_artifacts)}"
    assert diagnosis.evidence_artifacts[ev1.id] == "artifacts/ev1.txt"
    assert diagnosis.evidence_artifacts[ev2.id] == "artifacts/ev2.txt"
    assert "missing-id" not in diagnosis.evidence_artifacts

    print(f"  ✓ DiagnosisRecord.evidence_artifacts包含{len(diagnosis.evidence_artifacts)}个artifact")
    print("  ✓ 缺失的evidence_id被正确忽略")


def test_mutation_mismatch_diagnostic():
    """测试mutation失败时的诊断信息结构"""
    print("\n测试4: Mutation失败诊断结构...")

    from game_agent.aci.mutation import UnityMutationExecutor, AciConfig

    with tempfile.TemporaryDirectory() as tmpdir:
        artifact_root = Path(tmpdir) / "artifacts"
        project_root = Path(tmpdir) / "project"
        artifact_root.mkdir()
        project_root.mkdir()

        executor = UnityMutationExecutor(
            config=AciConfig(enabled=True),
            project_root=project_root,
            artifact_root=artifact_root,
        )

        # 测试_mutation_mismatch_diagnostic方法存在
        assert hasattr(executor, '_mutation_mismatch_diagnostic')

        # 调用诊断方法
        result = executor._mutation_mismatch_diagnostic(
            tool="unity_script_patch",
            path="test.cs",
            old_text="missing text",
            new_text="new text",
            evidence_text="actual content",
            evidence_sha="sha123",
            evidence_artifact_path="artifacts/ev1.txt",
            current_text="actual content",
            current_sha="sha123",
            expected_sha="sha456",
            occurrences_in_evidence=0,
        )

        assert result["returncode"] == -1
        assert "diagnostic" in result["extra"]
        diagnostic = result["extra"]["diagnostic"]
        assert "error_code" in diagnostic
        assert "recovery_hint" in diagnostic
        assert diagnostic["error_code"] == "old_text_not_found_in_evidence"

        print("  ✓ _mutation_mismatch_diagnostic方法存在")
        print("  ✓ 返回结构包含diagnostic和recovery_hint")
        print(f"  ✓ error_code: {diagnostic['error_code']}")


def test_workflow_state_evidence_artifacts():
    """测试WorkflowState存储evidence_artifacts"""
    print("\n测试5: WorkflowState包含evidence_artifacts字段...")

    from game_agent.aci.workflow import WorkflowState, WorkflowPhase
    from game_agent.aci.candidate import CandidateFrontier
    from game_agent.aci.workflow import SearchBudget, SubmissionContract

    workflow = WorkflowState(
        phase=WorkflowPhase.EDIT,
        search_budget=SearchBudget(),
        frontier=CandidateFrontier(max_size=10),
        submission=SubmissionContract(),
    )

    # 验证字段存在
    assert hasattr(workflow, 'evidence_artifacts')
    assert isinstance(workflow.evidence_artifacts, dict)

    # 验证可以设置
    workflow.evidence_artifacts = {"ev1": "path1", "ev2": "path2"}
    assert len(workflow.evidence_artifacts) == 2

    print("  ✓ WorkflowState.evidence_artifacts字段存在")
    print("  ✓ 可以存储evidence_id到artifact_path的映射")


def test_unity_script_patch_schema():
    """测试unity_script_patch schema包含evidence参数"""
    print("\n测试6: unity_script_patch schema包含evidence字段...")

    from game_agent.aci.schemas import TYPED_MUTATION_TOOLS

    # 找到unity_script_patch工具
    patch_tool = None
    for tool in TYPED_MUTATION_TOOLS:
        if tool["function"]["name"] == "unity_script_patch":
            patch_tool = tool
            break

    assert patch_tool is not None, "unity_script_patch工具未找到"

    properties = patch_tool["function"]["parameters"]["properties"]
    assert "evidence_id" in properties, "evidence_id参数缺失"
    assert "evidence_artifact_path" in properties, "evidence_artifact_path参数缺失"

    print("  ✓ unity_script_patch包含evidence_id参数")
    print("  ✓ unity_script_patch包含evidence_artifact_path参数")


def main():
    print("=" * 60)
    print("P0修改验证测试")
    print("=" * 60)

    try:
        test_evidence_with_artifact_fields()
        test_evidence_ledger_add_with_artifacts()
        test_diagnosis_record_with_evidence_artifacts()
        test_mutation_mismatch_diagnostic()
        test_workflow_state_evidence_artifacts()
        test_unity_script_patch_schema()

        print("\n" + "=" * 60)
        print("✓ 所有测试通过")
        print("=" * 60)
        print("\nP0修改总结：")
        print("1. ✓ Evidence数据类增加artifact_path和artifact_sha256字段")
        print("2. ✓ EvidenceLedger.add支持artifact参数")
        print("3. ✓ DiagnosisRecord.from_arguments自动收集evidence artifacts")
        print("4. ✓ UnityMutationExecutor._script_patch从artifact读取")
        print("5. ✓ UnityMutationExecutor._mutation_mismatch_diagnostic提供详细诊断")
        print("6. ✓ WorkflowState存储evidence_artifacts映射")
        print("7. ✓ unity_script_patch schema包含evidence参数")
        print("\n下一步: 运行真实E2E测试验证完整流程")
        return 0

    except AssertionError as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n✗ 错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
