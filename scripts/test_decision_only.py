"""Test Decision tool calling in isolation."""

import json
from pathlib import Path
from dotenv import load_dotenv

# Load .env
load_dotenv()

from game_agent_try.framework.models.litellm_model import LitellmModel

def test_mutation_tool():
    """Test that the model can call generate_mutations tool."""

    print("Testing generate_mutations tool call...")

    # Define mutation schema
    mutation_schema = {
        "type": "object",
        "properties": {
            "reasoning": {"type": "string"},
            "mutations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "old_text": {"type": "string"},
                        "new_text": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["file_path", "old_text", "new_text", "description"],
                },
            },
        },
        "required": ["reasoning", "mutations"],
    }

    # Define mutation tool
    mutation_tool = {
        "type": "function",
        "function": {
            "name": "generate_mutations",
            "description": "Generate code mutations to fix the Unity bug",
            "parameters": mutation_schema,
        }
    }

    # IMPORTANT: Register in TOOL_SCHEMAS before calling model
    from game_agent_try.framework.models.utils.actions_toolcall import TOOL_SCHEMAS
    original_schema = TOOL_SCHEMAS.copy()
    TOOL_SCHEMAS['generate_mutations'] = mutation_schema

    try:
        # Initialize model
        model = LitellmModel(
            model_name="openai/deepseek-v3",
            temperature=0.0,
            cost_tracking="ignore_errors",
            api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
            drop_params=True,
        )

        # Set only this tool
        model.agent_tools = [mutation_tool]

        messages = [
            {
                "role": "system",
                "content": "You are a Unity code mutation specialist. You MUST use the generate_mutations tool. Do NOT provide plain text responses."
            },
            {
                "role": "user",
                "content": """Generate a mutation to fix this bug:

Task: Player presses interact key at start screen, game should enter countdown.

File: Assets/Scripts/KitchenGameManager.cs
Issue: OnInteractAction callback is registered but state doesn't change

Fix: Call SetState(GameState.CountdownToStart) in OnInteractAction.

YOU MUST call the generate_mutations tool with:
- reasoning: explanation
- mutations: array with one mutation object

Call the tool NOW."""
            }
        ]

        print(f"Calling model with tool...")
        response = model.query(messages)

        print(f"\n✅ SUCCESS! Model called the tool")
        print(f"\nResponse keys: {response.keys()}")

        extra = response.get("extra", {})
        actions = extra.get('actions', [])
        print(f"Actions generated: {len(actions)}")

        if actions:
            print(f"\nFirst action:")
            print(json.dumps(actions[0], indent=2, ensure_ascii=False))
            return True
        else:
            print(f"❌ No actions in response")
            return False

    finally:
        # Restore TOOL_SCHEMAS
        TOOL_SCHEMAS.clear()
        TOOL_SCHEMAS.update(original_schema)

if __name__ == "__main__":
    test_mutation_tool()
