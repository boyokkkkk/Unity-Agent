"""Test tool calls format for different models."""
import os
from pathlib import Path
from dotenv import load_dotenv
import json
from game_agent_try.framework.models.litellm_model import LitellmModel

# Load environment variables
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"✓ Loaded .env from {env_path}")
else:
    print(f"⚠️  No .env file found at {env_path}")

def test_model_tool_calls(model_name: str, api_base: str = None):
    """Test what format a model returns for tool calls."""
    print(f"\n{'='*80}")
    print(f"Testing: {model_name}")
    print('='*80)

    kwargs = {
        "model_name": model_name,
        "temperature": 0.0,
        "cost_tracking": "ignore_errors",
        "drop_params": True,
    }

    if api_base:
        kwargs["api_base"] = api_base
        print(f"   Using API base: {api_base}")

    model = LitellmModel(**kwargs)

    # Simple test tool
    test_tool = {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search for code in the project",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query"
                    }
                },
                "required": ["query"]
            }
        }
    }

    messages = [
        {
            "role": "system",
            "content": "You are a code assistant. Use the search_code tool to search."
        },
        {
            "role": "user",
            "content": "Search for 'GameManager' in the code. You MUST use the search_code tool."
        }
    ]

    print(f"\n📤 Sending request...")
    print(f"   Tools: {test_tool['function']['name']}")

    try:
        # Manually call litellm to bypass our parsing
        import litellm
        response = litellm.completion(
            model=model_name,
            messages=messages,
            tools=[test_tool],
        )

        print(f"\n✅ API call succeeded!")
        print(f"\n📊 Response structure:")
        print(f"   Type: {type(response)}")
        print(f"   Has choices: {hasattr(response, 'choices')}")

        if hasattr(response, 'choices') and response.choices:
            message = response.choices[0].message
            print(f"\n📨 Message structure:")
            print(f"   Type: {type(message)}")
            print(f"   Has tool_calls: {hasattr(message, 'tool_calls')}")
            print(f"   Has function_call: {hasattr(message, 'function_call')}")
            print(f"   Content: {getattr(message, 'content', None)}")

            if hasattr(message, 'tool_calls') and message.tool_calls:
                print(f"\n🔧 Tool calls found: {len(message.tool_calls)}")
                for i, tc in enumerate(message.tool_calls):
                    print(f"\n   Tool call #{i+1}:")
                    print(f"      Type: {type(tc)}")
                    print(f"      Has id: {hasattr(tc, 'id')}")
                    print(f"      Has function: {hasattr(tc, 'function')}")

                    if hasattr(tc, 'function'):
                        func = tc.function
                        print(f"      Function type: {type(func)}")
                        print(f"      Function name: {getattr(func, 'name', None)}")
                        print(f"      Arguments type: {type(getattr(func, 'arguments', None))}")
                        print(f"      Arguments: {getattr(func, 'arguments', None)}")

                    # Try to dump as dict
                    try:
                        if hasattr(tc, 'model_dump'):
                            print(f"\n      Full dump:")
                            print(json.dumps(tc.model_dump(), indent=8, ensure_ascii=False))
                        elif hasattr(tc, 'dict'):
                            print(f"\n      Full dump:")
                            print(json.dumps(tc.dict(), indent=8, ensure_ascii=False))
                    except Exception as e:
                        print(f"      Could not dump: {e}")

            elif hasattr(message, 'function_call'):
                print(f"\n📞 Function call (old format):")
                print(f"   {message.function_call}")
            else:
                print(f"\n⚠️  No tool_calls or function_call found!")
                print(f"\n   Message attributes:")
                for attr in dir(message):
                    if not attr.startswith('_'):
                        print(f"      {attr}: {getattr(message, attr, None)}")

        print(f"\n✅ {model_name}: Tool calls format identified")
        return True

    except Exception as e:
        print(f"\n❌ {model_name}: Error")
        print(f"   {type(e).__name__}: {e}")
        import traceback
        print(f"\n   Traceback:")
        print(traceback.format_exc())
        return False

if __name__ == "__main__":
    print("🧪 Tool Calls Format Diagnostic")
    print("=" * 80)

    # DashScope endpoint
    dashscope_base = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # Test models available via DashScope
    models_to_test = [
        ("openai/qwen-plus", dashscope_base),
        ("openai/deepseek-v3", dashscope_base),
    ]

    results = {}
    for model_name, api_base in models_to_test:
        results[model_name] = test_model_tool_calls(model_name, api_base)

    print(f"\n\n{'='*80}")
    print("📊 Summary")
    print('='*80)
    for model_name, success in results.items():
        status = "✅" if success else "❌"
        print(f"{status} {model_name}")
