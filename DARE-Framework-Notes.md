# DARE Framework 实践笔记

> 本文记录了基于 DARE Framework (Deterministic-Agent-Runtime-Engine) 构建服务化 Agent 的完整过程，包括框架架构、组件理解、记忆设计、扩展方法。

---

## 目录

- [一、DARE Framework 核心架构](#一dare-framework-核心架构)
- [二、我们构建的 dare-time-agent-demo 架构流程](#二我们构建的dare-time-agent-demo架构流程)
- [三、短期记忆 (Short-Term Memory) 理解](#三短期记忆-short-term-memory-理解)
- [四、长期记忆 (Long-Term Memory) 理解与改造方案](#四长期记忆-long-term-memory-理解与改造方案)
- [五、扩展功能清单](#五扩展功能清单)
- [六、常见问题排查](#六常见问题排查)

---

## 一、DARE Framework 核心架构

DARE Framework 采用**五层编排架构**，每层职责清晰：

```
┌─────────────────────────────────────────────────────────────┐
│                     第一层: Session Loop                      │
│  (run_session_loop) 顶层任务生命周期管理                       │
│  • 功能：初始化会话状态，驱动整个任务完成                        │
│  • 约束：一个会话对应一个 task_id                              │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                     第二层: Milestone Loop                    │
│  (run_milestone_loop) 子目标分解与验证                         │
│  • 功能：将大任务分解为多个里程碑，逐个验证完成                 │
│  • 约束：每个里程碑必须提供可验证的证据                        │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                       第三层: Plan Loop                        │
│  Planner → Validator → Remediator 规划生成验证修复循环         │
│  • Planner (DefaultPlanner): 生成 JSON 格式计划               │
│  • Validator: 验证计划合理性                                   │
│  • Remediator (DefaultRemediator): 如果规划失败，尝试修复      │
│  • 约束：输出必须是符合格式的 JSON                              │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                       第四层: Execute Loop                     │
│  (run_execute_loop) 执行规划出的每个步骤                       │
│  • 功能：按计划逐个执行步骤，收集证据                          │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                         第五层: Tool Loop                      │
│  (run_tool_loop) 单步工具调用循环                              │
│  • 功能：准备工具调用 → 调用 LLM 生成工具参数 → 执行工具 → 返回结果 │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                     结果原路返回 → 汇总 → 最终回答             │
└─────────────────────────────────────────────────────────────┘
```

### 核心组件职责

| 组件 | 职责 |
|------|------|
| **DareAgentBuilder** | 建造者模式，组装各个组件 |
| **IModelAdapter** | 大模型 API 适配，统一接口 |
| **Planner** | 理解任务，生成结构化执行计划 |
| **Remediator** | 规划/执行失败时尝试修复 |
| **ITool** | 自定义工具抽象接口 |
| **SkillStore** | 技能仓库，动态加载外部技能 |
| **McpToolManager** | 管理 MCP (Model Context Protocol) 服务器连接 |
| **Short-Term Memory** | 当前任务上下文存储 |
| **Long-Term Memory** | 跨会话知识/记忆存储 |

---

## 二、我们构建的 dare-time-agent-demo 架构流程

### 项目结构

```
/Users/daluzi/.openclaw/workspace/
├── dare-time-agent-demo.py       # 主程序，FastAPI 服务
├── test_model_api.py             # 独立大模型 API 测试脚本
├── skills/                       # 技能目录（用户可见，可编辑）
│   └── time-faq.yaml             # 时间常见问题示例技能
├── .dare/                        # DARE 框架配置目录（隐藏）
│   └── mcp/
│       └── config.json          # MCP 服务器配置
├── .ltm_data/                    # 长期向量记忆存储（运行后生成）
└── DARE-Framework-Notes.md       # 本笔记
```

### 处理流程

```
用户发送 HTTP POST /query
    ↓
ManagedAgent.run_query(question)
    ↓
构造 Message 对象（解决 'str has no attribute metadata' 问题）
    ↓
agent.execute(message)
    ↓
进入五层编排 → 最终得到结果
    ↓
格式化为 JSON 返回给用户
```

### 已集成功能

- ✅ **自定义工具**：
  - `get_current_time` - 获取当前时间，支持时区
  - `get_system_info` - 获取系统信息（CPU/内存/磁盘）
  - `calculate_date_diff` - 计算两个日期相差天数
- ✅ **技能加载**：自动加载 `./skills` 目录下的 YAML/Markdown 技能，提供 `search_skill` 工具
- ✅ **MCP 支持**：自动加载 `./.dare/mcp/config.json` 中的 MCP 服务器配置
- ✅ **长期记忆**：优先向量存储，失败回退到内存存储，提供 `knowledge_add` / `knowledge_get` 工具

### API 端点

| 端点 | 方法 | 功能 |
|------|------|------|
| `/query` | POST | 向 Agent 发送查询 |
| `/skills/reload` | POST | 动态重新加载技能，无需重启 |
| `/mcp/reload` | POST | 动态重新加载 MCP 配置，无需重启 |
| `/status` | GET | 获取服务状态 |

---

## 三、短期记忆 (Short-Term Memory) 理解

### 当前方案

我们使用 `InMemorySTM`：

- **存储位置**：进程内存
- **生命周期**：单次查询执行过程
- **核心作用**：单个 query 对应的**整个执行流程上下文管理**

### 正确理解粒度

| 支持 / 不支持 | 说明 |
|--------------|------|
| ✅ 支持 **单查询内多步骤** | 五层编排的每一步中间结果（计划、工具调用结果等）都存在这里，供后续步骤读取 |
| ❌ 默认不支持 **跨查询多轮对话** | 每次查询执行完后会重置，上一轮对话不会自动带到下一次 |

### 常见问题

> Q: 能不能说"它只是单轮，不支持多轮"？
>
> A: 需要修正：它支持单 query 内的**多步骤**（这是五层架构必须的），不支持的是**跨 query** 的多轮对话。

### 如果需要跨查询多轮对话怎么办？

两种方案：

1. **利用长期记忆**：每轮结束后将对话存入 LTM，下一轮开始前检索出来
2. **改造代码按 conversation_id 保存 STM**：用户请求带 conversation_id，取出对应 STM 继续对话（需要自己处理过期清理）

---

## 四、长期记忆 (Long-Term Memory) 理解与改造方案

### 当前方案（分级回退）

我们实现了自动降级：

```python
try:
    # 方案一：向量持久化存储（优先）
    embedding_adapter = OpenAIEmbeddingAdapter(...)
    ltm = create_long_term_memory({
        "type": "vector",
        "storage": "chromadb",
        "collection_name": "dare_time_agent_memory",
        "persist_directory": "./.ltm_data"
    }, embedding_adapter)
except Exception:
    # 方案二：回退到简单内存存储
    ltm = create_long_term_memory({
        "type": "rawdata",
        "storage": "in_memory"
    }, None)
```

### 对比

| 特性 | vector + chromadb | rawdata + in_memory |
|------|-------------------|---------------------|
| 存储 | 本地磁盘持久化 | 进程内存 |
| 检索 | 语义相似度检索 | 关键词匹配 |
| 重启 | 数据不丢失 | 数据丢失 |
| 依赖 | 需要 chromadb + embedding API | 无依赖 |

### 服务端改造：独立长期记忆服务接入

对于服务端场景，需要**用户隔离**、独立维护，可以替换自定义实现：

#### 1. DARE 设计本身支持：基于 `ILongTermMemory` 接口

```python
from dare_framework.memory.kernel import ILongTermMemory
from typing import List, Tuple

class RemoteServiceLongTermMemory(ILongTermMemory):
    """调用独立长期记忆服务"""
    
    def __init__(self, service_url: str, api_key: str):
        self.service_url = service_url
        self.api_key = api_key
    
    async def add(self, content: str, metadata: dict|None = None, user_id: str|None = None) -> bool:
        # 调用你的远程服务添加记忆
        # user_id 参数用于用户隔离
        pass
    
    async def search(self, query: str, top_k: int = 5, user_id: str|None = None) -> List[Tuple[str, float]]:
        # 调用你的远程服务检索
        # 按 user_id 过滤，只返回该用户的记忆
        pass
    
    async def delete(self, memory_id: str, user_id: str|None = None) -> bool:
        # 删除指定记忆
        pass
    
    async def clear(self, user_id: str|None = None) -> bool:
        # 清空用户所有记忆
        pass
```

#### 2. 使用方式

```python
# 在 initialize() 中替换
ltm = RemoteServiceLongTermMemory(
    service_base_url="http://your-memory-service:8080/api",
    api_key=os.getenv("MEMORY_SERVICE_API_KEY", "")
)
```

#### 3. 最终架构

```
┌─────────────────┐
│  API 网关       │
└────────┐        │
         ▼
┌──────────────────────────────────┐
│  dare-time-agent-demo (DARE)     │
│                                  │
│  ┌─────────────┐  ┌──────────┐  │
│  │ 短期记忆    │  │  工具    │  │
│  │  InMemory   │  │ 规划执行 │  │
│  └─────────────┘  └──────────┘  │
│              ↓                   │
│  ILongTermMemory 接口            │
│     ↓ 你的自定义实现             │
└──────────────────────┬───────────┘
                       │
                       ▼
        ┌───────────────────────────┐
        │   你的独立长期记忆服务      │
        │   - 用户级隔离存储         │
        │   - 向量持久化             │
        │   - 语义检索               │
        │   - 记忆抽取/整理          │
        └───────────────────────────┘
```

### 关键点

- ✅ **完全可替换** - 依赖抽象接口，不绑死实现
- ✅ **用户隔离支持** - `add/search` 都有 `user_id` 参数，隔离逻辑你自己控制
- ✅ **能力可扩展** - 记忆抽取、过期清理、压缩都可以在独立服务实现

---

## 五、扩展功能清单

### 添加更多自定义工具

步骤：

1. 实现 `ITool` 接口，必须实现所有属性和 `execute` 方法
2. 在 `builder.add_tools(YourTool())` 添加

示例：

```python
class YourTool(ITool):
    @property
    def id(self) -> str: return "your_tool"
    @property
    def name(self) -> str: return "your_tool"
    @property
    def description(self) -> str: return "工具描述"
    @property
    def risk_level(self) -> RiskLevelName: return "read_only"
    @property
    def tool_type(self) -> ToolType: return ToolType.ATOMIC
    @property
    def capability_kind(self) -> CapabilityKind: return CapabilityKind.TOOL
    @property
    def is_work_unit(self) -> bool: return False
    @property
    def requires_approval(self) -> bool: return False
    @property
    def timeout_seconds(self) -> int: return 10
    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {...},
            "required": [...]
        }
    async def execute(self, *, run_context: RunContext[Any], ...) -> ToolResult:
        # 实现逻辑
        return ToolResult(success=True, output=result)
```

### 添加技能

步骤：

1. 在 `./skills/` 创建 `.yaml` 或 `.md` 文件
2. YAML 格式需要包含 `skill_id`、`name`、`description`、`content`
3. 调用 `POST /skills/reload` 生效，无需重启

### 配置 MCP

步骤：

1. 在 `./.dare/mcp/config.json` 添加服务器配置（格式兼容 Claude Desktop）
2. 调用 `POST /mcp/reload` 生效，无需重启

> 为什么放 `.dare` 不放在 `dare`？
> - 约定：框架系统配置隐藏，用户技能可见
> - `.dare` 是隐藏目录，不干扰主目录结构
> - 避免和用户代码冲突

---

## 六、常见问题排查

### 1. `AttributeError: 'str' object has no attribute 'metadata'`

**原因**：`execute()` 需要 `Message` 对象，传入了字符串

**修复**：在调用前构造 `Message`：

```python
message = Message(
    role=MessageRole.USER,
    kind=MessageKind.CHAT,
    text=question
)
result = await agent.execute(message)
```

### 2. `ToolResult.__init__() got an unexpected keyword argument 'content'`

**原因**：`ToolResult` 没有 `content` 参数，只有 `output` 和 `error`

**修复**：把内容放到 `output` 里：

```python
# 错误写法
return ToolResult(success=True, output=result, content="text")
# 正确写法
result["content"] = "text"
return ToolResult(success=True, output=result)
```

### 3. 大模型不调用工具，直接回答

**原因**：系统提示词没有明确告诉它必须调用工具

**修复**：在 Planner 的 `system_prompt` 中明确说明："当用户问 X 时，必须调用 Y 工具"

### 4. `InternalServerError` 调用大模型失败

**解决方法**：用 `test_model_api.py` 单独测试：

```bash
export OPENROUTER_API_KEY=your-key
export OPENROUTER_MODEL=your-model
export OPENROUTER_BASE_URL=your-base-url
python test_model_api.py
```

它会打印详细错误信息帮助定位。

### 5. 为什么 MCP 连接失败不报错，服务还能启动？

**原因**：代码中设置了 `skip_errors=True`，一个 MCP 连接失败不影响其他功能

```python
self.mcp_clients = create_mcp_clients(configs, connect=True, skip_errors=True)
```

---

## 总结

DARE Framework 的设计哲学：

- **组件化**：所有核心组件都基于接口，可替换
- **分层编排**：五层职责清晰，每层只做一件事
- **渐进式扩展**：从简单 demo 到生产级服务，可以逐步扩展
- **不绑架实现**：默认提供开箱即用的示例，需要时可以完全替换存储/模型/规划

---

**最后更新**：2026-03-27
