"""Direct mutation test to debug ACI workflow."""
import sys
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Add project to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from game_agent_try.aci.mutation import UnityMutationExecutor, AciConfig

def test_mutation():
    """Test a simple mutation with artifact."""

    unity_root = Path(r"E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos")
    artifact_root = unity_root / ".game-agent-artifacts"

    print(f"Unity root: {unity_root}")
    print(f"Artifact root: {artifact_root}")

    # Create executor
    config = AciConfig()
    executor = UnityMutationExecutor(
        project_root=unity_root,
        artifact_root=artifact_root,
        config=config,
    )

    # Test action - use actual code format
    action = {
        "tool": "unity_script_patch",
        "arguments": {
            "path": "Assets/Scripts/KitchenGameManager.cs",
            "old_text": "    private void Start()\r\n    {",
            "new_text": "    private void Start()\r\n    {\r\n        // Test comment added by ACI",
            "expected_sha256": "f0f5bb48031bb4e9c3af662c3c5435e0b0ed030be1500441b022b7d842d7da6f",
            "evidence_artifact_path": "evidence-artifacts/evidence_e8c70e1fc452463f.txt",
        },
        "_authorized_paths": ["Assets/Scripts/KitchenGameManager.cs"],
    }

    print("\n" + "="*80)
    print("Executing mutation...")
    print("="*80)

    result = executor.execute(action)

    print("\n" + "="*80)
    print("Result:")
    print("="*80)
    print(f"Returncode: {result.get('returncode')}")

    extra = result.get('extra', {})
    structured = extra.get('structured', {})
    status = structured.get('status')

    print(f"Status: {status}")

    if status in ("success", "ok"):
        print("✅ SUCCESS!")
        print(f"Transaction ID: {structured.get('transaction_id')}")
        print(f"Changed paths: {structured.get('changed_paths')}")
    else:
        print("❌ FAILED!")
        print(f"Message: {structured.get('message')}")
        if 'diagnostic' in extra:
            diag = extra['diagnostic']
            print(f"\nDiagnostic:")
            print(f"  Error code: {diag.get('error_code')}")
            print(f"  Evidence SHA: {diag.get('evidence_sha')}")
            print(f"  Current SHA: {diag.get('current_sha')}")
            print(f"  Expected SHA: {diag.get('expected_sha')}")

if __name__ == "__main__":
    test_mutation()
