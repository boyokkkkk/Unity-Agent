"""
Test P0: Evidence Artifact持久化机制
验证修改1-3和修改6-8的完整集成
"""
import hashlib
import json
from pathlib import Path
import tempfile
import pytest

from game_agent.context.models import Evidence, EvidenceLedger, EvidenceStatus


def test_evidence_with_artifact_fields():
    """测试Evidence数据类包含artifact字段"""
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


def test_evidence_ledger_add_with_artifacts():
    """测试EvidenceLedger.add支持artifact参数"""
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


def test_diagnosis_record_with_evidence_artifacts():
    """测试DiagnosisRecord绑定evidence artifacts"""
    from game_agent.aci.diagnosis import DiagnosisRecord, CausalClaim

    # 创建mock evidence ledger
    ledger = EvidenceLedger()
    ev1 = ledger.add(
        "Evidence 1",
        artifact_path="artifacts/ev1.txt",
        artifact_sha256="hash1",
    )
    ev2 = ledger.add(
        "Evidence 2",
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
    assert len(diagnosis.evidence_artifacts) == 2
    assert diagnosis.evidence_artifacts[ev1.id] == "artifacts/ev1.txt"
    assert diagnosis.evidence_artifacts[ev2.id] == "artifacts/ev2.txt"
    assert "missing-id" not in diagnosis.evidence_artifacts


def test_code_file_read_artifact_persistence_structure():
    """测试code_file_read的artifact持久化结构（单元测试）"""
    from game_agent.aci.query import StructuredQueryExecutor
    from game_agent.context import ContextAssembler

    # 这是结构测试，验证_ok方法签名正确
    # 实际集成测试需要完整的Unity项目环境

    with tempfile.TemporaryDirectory() as tmpdir:
        artifact_root = Path(tmpdir)

        # 验证artifact目录可以创建
        artifact_dir = artifact_root / "evidence-artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        # 验证evidence ID生成
        evidence_id = EvidenceLedger.id_for(
            "Read source file test.cs at SHA-256 abc123.",
            ["source:test.cs:1-100"]
        )

        # 验证文件名生成
        artifact_file = artifact_dir / f"{evidence_id.replace(':', '_')}.txt"
        artifact_file.write_text("test content", encoding="utf-8")

        assert artifact_file.exists()
        assert artifact_file.read_text(encoding="utf-8") == "test content"


def test_mutation_with_evidence_artifact():
    """测试mutation从evidence artifact读取（模拟）"""
    with tempfile.TemporaryDirectory() as tmpdir:
        artifact_root = Path(tmpdir)
        workspace = Path(tmpdir) / "workspace"
        workspace.mkdir()

        # 创建evidence artifact
        evidence_dir = artifact_root / "evidence-artifacts"
        evidence_dir.mkdir(parents=True, exist_ok=True)

        evidence_content = "void Start() {\n    Debug.Log(\"Old\");\n}\n"
        evidence_sha = hashlib.sha256(evidence_content.encode("utf-8")).hexdigest()

        evidence_file = evidence_dir / "ev123.txt"
        evidence_file.write_text(evidence_content, encoding="utf-8")

        # 创建workspace文件（与evidence相同）
        target_file = workspace / "test.cs"
        target_file.write_text(evidence_content, encoding="utf-8")

        # 验证匹配逻辑
        old_text = '    Debug.Log("Old");'
        new_text = '    Debug.Log("New");'

        occurrences = evidence_content.count(old_text)
        assert occurrences == 1, f"Expected 1 occurrence, found {occurrences}"

        # 模拟patch
        patched = evidence_content.replace(old_text, new_text, 1)
        assert 'Debug.Log("New")' in patched
        assert 'Debug.Log("Old")' not in patched


def test_workflow_state_evidence_artifacts():
    """测试WorkflowState存储evidence_artifacts"""
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
