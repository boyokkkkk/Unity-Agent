# 支持Tool Calls的模型推荐

## 🎯 兼容性分析

### Tool Calls支持要求
- 支持OpenAI格式的function calling
- 返回标准的tool_calls格式
- LiteLLM支持

---

## 🌟 推荐模型列表

### Tier 1: 完全兼容 (推荐)

#### 1. **OpenAI系列** ⭐⭐⭐⭐⭐
```python
# GPT-4o mini (最推荐 - 性价比高)
model = LitellmModel(model_name="gpt-4o-mini", temperature=0.3)
# 价格: ~$0.15/1M input, ~$0.60/1M output
# 质量: 优秀
# 速度: 快

# GPT-4o (最强但贵)
model = LitellmModel(model_name="gpt-4o", temperature=0.3)
# 价格: ~$5/1M input, ~$15/1M output
# 质量: 顶级
# 速度: 快

# GPT-3.5 Turbo (便宜)
model = LitellmModel(model_name="gpt-3.5-turbo", temperature=0.3)
# 价格: ~$0.50/1M input, ~$1.50/1M output
# 质量: 良好
# 速度: 很快
```

**优点:**
- ✅ Tool calls标准制定者，100%兼容
- ✅ LiteLLM完美支持
- ✅ 文档齐全
- ✅ 稳定可靠

**缺点:**
- ⚠️ 需要OpenAI API key
- ⚠️ 国内需要代理

---

#### 2. **Anthropic Claude** ⭐⭐⭐⭐⭐
```python
# Claude 3.5 Sonnet (推荐)
model = LitellmModel(model_name="claude-3-5-sonnet-20241022", temperature=0.3)
# 价格: ~$3/1M input, ~$15/1M output
# 质量: 顶级
# 速度: 快

# Claude 3 Haiku (便宜快速)
model = LitellmModel(model_name="claude-3-haiku-20240307", temperature=0.3)
# 价格: ~$0.25/1M input, ~$1.25/1M output
# 质量: 良好
# 速度: 很快
```

**优点:**
- ✅ Tool use支持优秀
- ✅ 代码理解能力强
- ✅ LiteLLM完美支持
- ✅ 长上下文能力强

**缺点:**
- ⚠️ 需要Anthropic API key
- ⚠️ 价格较高

---

### Tier 2: 兼容性好

#### 3. **Deepseek** ⭐⭐⭐⭐
```python
# Deepseek Chat (国内友好)
model = LitellmModel(
    model_name="deepseek/deepseek-chat",
    temperature=0.3,
    api_base="https://api.deepseek.com/v1"
)
# 价格: ~$0.14/1M input, ~$0.28/1M output (非常便宜!)
# 质量: 良好
# 速度: 快
```

**优点:**
- ✅ 国内可直接访问
- ✅ 价格极低
- ✅ 支持function calling
- ✅ 代码能力强

**缺点:**
- ⚠️ Tool calls兼容性未知（需要测试）
- ⚠️ 文档相对少

---

#### 4. **通义千问 Qwen-Max/Qwen-Turbo** ⭐⭐⭐
```python
# Qwen-Max (最强版本)
model = LitellmModel(
    model_name="qwen/qwen-max",
    temperature=0.3,
)

# Qwen-Turbo (便宜快速)
model = LitellmModel(
    model_name="qwen/qwen-turbo",
    temperature=0.3,
)
```

**分析:**
- qwen-plus已知有兼容性问题
- qwen-max可能更好（更新的版本）
- 需要测试验证

---

#### 5. **Google Gemini** ⭐⭐⭐⭐
```python
# Gemini 1.5 Flash (推荐 - 性价比高)
model = LitellmModel(
    model_name="gemini/gemini-1.5-flash",
    temperature=0.3,
)
# 价格: ~$0.075/1M input, ~$0.30/1M output
# 质量: 优秀
# 速度: 很快

# Gemini 1.5 Pro
model = LitellmModel(
    model_name="gemini/gemini-1.5-pro",
    temperature=0.3,
)
# 价格: ~$1.25/1M input, ~$5/1M output
# 质量: 顶级
# 速度: 快
```

**优点:**
- ✅ Function calling支持好
- ✅ 价格低
- ✅ 长上下文 (1M+ tokens)
- ✅ LiteLLM支持

**缺点:**
- ⚠️ 需要Google API key
- ⚠️ 国内访问可能需要代理

---

### Tier 3: 开源/本地模型

#### 6. **Ollama本地模型** ⭐⭐⭐
```python
# Llama 3.1 70B (需要本地部署)
model = LitellmModel(
    model_name="ollama/llama3.1:70b",
    temperature=0.3,
    api_base="http://localhost:11434"
)
```

**优点:**
- ✅ 完全免费
- ✅ 数据隐私
- ✅ 无限调用

**缺点:**
- ⚠️ 需要强大的本地硬件
- ⚠️ Tool calls支持不完善
- ⚠️ 质量可能不如商业模型

---

## 📊 综合推荐

### 最佳选择 (按场景)

#### 场景1: 快速验证Phase 1 
**推荐: GPT-4o-mini** ⭐⭐⭐⭐⭐
```python
model = LitellmModel(model_name="gpt-4o-mini", temperature=0.3)
```
- 原因: 兼容性最好，价格合理，速度快
- 预估成本: ~$0.50 完成Phase 1测试

#### 场景2: 国内友好 + 低成本
**推荐: Deepseek Chat** ⭐⭐⭐⭐
```python
model = LitellmModel(
    model_name="deepseek/deepseek-chat",
    temperature=0.3,
    api_base="https://api.deepseek.com/v1"
)
```
- 原因: 国内直连，价格极低，质量不错
- 预估成本: ~$0.10 完成Phase 1测试

#### 场景3: 最强性能
**推荐: Claude 3.5 Sonnet** ⭐⭐⭐⭐⭐
```python
model = LitellmModel(model_name="claude-3-5-sonnet-20241022", temperature=0.3)
```
- 原因: 代码理解最强，tool use优秀
- 预估成本: ~$2.00 完成Phase 1测试

#### 场景4: 极致性价比
**推荐: Gemini 1.5 Flash** ⭐⭐⭐⭐
```python
model = LitellmModel(model_name="gemini/gemini-1.5-flash", temperature=0.3)
```
- 原因: 价格最低，质量优秀，速度快
- 预估成本: ~$0.30 完成Phase 1测试

---

## 🧪 测试策略

### 快速兼容性测试脚本

```python
# test_model_compatibility.py
from game_agent_try.framework.models.litellm_model import LitellmModel

def test_tool_calls(model_name, **kwargs):
    """Test if a model supports tool calls correctly"""
    model = LitellmModel(model_name=model_name, temperature=0.3, **kwargs)
    
    test_tool = {
        "type": "function",
        "function": {
            "name": "test_function",
            "description": "A test function",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string"}
                },
                "required": ["message"]
            }
        }
    }
    
    try:
        response = model.query(
            messages=[
                {"role": "system", "content": "You are a helpful assistant. Use the test_function."},
                {"role": "user", "content": "Call test_function with message='hello'"}
            ],
            tools=[test_tool],
        )
        
        tool_calls = response.get("tool_calls")
        if tool_calls:
            print(f"✅ {model_name}: Tool calls working!")
            print(f"   Format: {tool_calls[0]}")
            return True
        else:
            print(f"⚠️  {model_name}: No tool calls in response")
            return False
            
    except Exception as e:
        print(f"❌ {model_name}: Error - {e}")
        return False

# Test candidates
models_to_test = [
    ("gpt-4o-mini", {}),
    ("deepseek/deepseek-chat", {"api_base": "https://api.deepseek.com/v1"}),
    ("gemini/gemini-1.5-flash", {}),
    ("qwen/qwen-max", {}),
]

for model_name, kwargs in models_to_test:
    test_tool_calls(model_name, **kwargs)
```

---

## 💰 成本对比 (Phase 1测试预估)

| 模型 | Input Tokens | Output Tokens | 预估成本 | 推荐度 |
|------|-------------|---------------|----------|--------|
| GPT-4o-mini | 60k | 10k | ~$0.50 | ⭐⭐⭐⭐⭐ |
| GPT-3.5-turbo | 60k | 10k | ~$0.80 | ⭐⭐⭐⭐ |
| Claude Haiku | 60k | 10k | ~$0.40 | ⭐⭐⭐⭐⭐ |
| Claude Sonnet | 60k | 10k | ~$2.00 | ⭐⭐⭐⭐ |
| Deepseek Chat | 60k | 10k | ~$0.10 | ⭐⭐⭐⭐⭐ |
| Gemini Flash | 60k | 10k | ~$0.30 | ⭐⭐⭐⭐⭐ |
| Qwen-Max | 60k | 10k | ~$0.20 | ⭐⭐⭐ |

---

## 🎯 我的推荐

### Top 3 选择:

**1. GPT-4o-mini** 
- 最稳妥的选择
- 100%兼容保证
- 价格合理

**2. Deepseek Chat**
- 国内友好
- 价格最低
- 值得一试

**3. Gemini 1.5 Flash**
- 性价比最高
- 质量优秀
- 速度快

---

## 📝 建议行动

1. **优先级1:** 试试Deepseek Chat (国内直连 + 便宜)
2. **优先级2:** 如果Deepseek有问题，用GPT-4o-mini (稳)
3. **优先级3:** 如果都不行，试Gemini Flash (便宜)

需要我帮你配置其中任何一个吗？
