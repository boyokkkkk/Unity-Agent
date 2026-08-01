"""Phase 0 verification script.

This script validates the basic functionality of the service layer:
- MutationService
- ValidationService
- SubmissionController
"""

from pathlib import Path
from game_agent_try.agents.models import (
    TaskComplexity,
    ComplexityAssessment,
    EvidencePackage,
    MutationResult,
    ValidationResult,
)
from game_agent_try.services import (
    MutationService,
    ValidationService,
    SubmissionController,
)


def test_models():
    """Test that all data models can be instantiated."""
    print("Testing data models...")

    # Test ComplexityAssessment
    assessment = ComplexityAssessment(
        level=TaskComplexity.SIMPLE,
        reasoning="Task has explicit location",
        estimated_files=1,
        needs_exploration=False,
        needs_critic=False,
        direct_execution_safe=True,
        required_tools=["unity_script_patch"],
    )
    assert assessment.level == TaskComplexity.SIMPLE
    print("  ✓ ComplexityAssessment")

    # Test MutationResult
    mutation_result = MutationResult(
        success=True,
        transaction_id="tx-123",
        checkpoint_id="cp-456",
        changed_paths=["Assets/Script.cs"],
        error=None,
    )
    assert mutation_result.success is True
    print("  ✓ MutationResult")

    # Test ValidationResult
    validation_result = ValidationResult(
        success=True,
        failed_mode=None,
        error=None,
        completed_modes=["compile", "editmode"],
    )
    assert validation_result.success is True
    print("  ✓ ValidationResult")

    print("✓ All data models working correctly\n")


def test_mutation_service():
    """Test MutationService initialization and stats."""
    print("Testing MutationService...")

    project_root = Path(__file__).parent.parent / "test_project"
    service = MutationService(project_root=project_root)

    # Test initialization
    assert service.execution_count == 0
    assert service.success_count == 0
    assert service.failure_count == 0
    print("  ✓ Initialization")

    # Test stats
    stats = service.get_stats()
    assert stats["total_executions"] == 0
    assert stats["successes"] == 0
    assert stats["failures"] == 0
    print("  ✓ Stats tracking")

    print("✓ MutationService working correctly\n")


def test_validation_service():
    """Test ValidationService initialization and stats."""
    print("Testing ValidationService...")

    project_root = Path(__file__).parent.parent / "test_project"
    service = ValidationService(project_root=project_root)

    # Test initialization
    assert service.validation_count == 0
    assert service.success_count == 0
    assert service.failure_count == 0
    print("  ✓ Initialization")

    # Test stats
    stats = service.get_stats()
    assert stats["total_validations"] == 0
    assert stats["successes"] == 0
    assert stats["failures"] == 0
    print("  ✓ Stats tracking")

    print("✓ ValidationService working correctly\n")


def test_submission_controller():
    """Test SubmissionController initialization and checking."""
    print("Testing SubmissionController...")

    project_root = Path(__file__).parent.parent / "test_project"
    config = {
        "mutation_required": True,
        "allow_no_change_submission": False,
        "required_validation_modes": ["editmode", "playmode"],
    }
    controller = SubmissionController(project_root=project_root, config=config)

    # Test initialization
    assert controller.check_count == 0
    assert controller.submission_count == 0
    print("  ✓ Initialization")

    # Test complete contract
    check = controller.check_submission_contract(
        diagnosis_present=True,
        mutation_count=1,
        completed_validation_modes=["editmode", "playmode"],
        review_passed=True,
    )
    assert check.ready is True
    assert len(check.missing_requirements) == 0
    print("  ✓ Complete contract check")

    # Test incomplete contract
    check = controller.check_submission_contract(
        diagnosis_present=False,
        mutation_count=0,
        completed_validation_modes=[],
        review_passed=False,
    )
    assert check.ready is False
    assert len(check.missing_requirements) > 0
    print("  ✓ Incomplete contract check")

    # Test report generation
    report = controller.generate_submission_report(
        task_description="Test task",
        diagnosis="Test diagnosis",
        changed_paths=["Assets/Test.cs"],
        completed_validation_modes=["editmode", "playmode"],
        mutation_count=1,
    )
    assert "Test task" in report
    assert "Test diagnosis" in report
    assert controller.submission_count == 1
    print("  ✓ Report generation")

    # Test stats
    stats = controller.get_stats()
    assert stats["total_checks"] == 2
    assert stats["submissions"] == 1
    print("  ✓ Stats tracking")

    print("✓ SubmissionController working correctly\n")


def main():
    """Run all Phase 0 verification tests."""
    print("=" * 60)
    print("Phase 0 Verification - Service Layer")
    print("=" * 60)
    print()

    try:
        test_models()
        test_mutation_service()
        test_validation_service()
        test_submission_controller()

        print("=" * 60)
        print("✓ Phase 0 verification complete!")
        print("=" * 60)
        print()
        print("Summary:")
        print("  - Data models: All working")
        print("  - MutationService: Zero-token wrapper ready")
        print("  - ValidationService: Zero-token wrapper ready")
        print("  - SubmissionController: Zero-token checker ready")
        print()
        print("Next step: Phase 1 - Implement Explorer Agent")

    except Exception as e:
        print(f"\n✗ Verification failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
