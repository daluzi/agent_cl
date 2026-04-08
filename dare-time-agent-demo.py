"""
DARE Framework 服务化 Agent Demo
功能：
1. 提供查询当前时间的基础能力
2. 支持动态加载 Skill 和 MCP
3. 服务化部署，暴露 HTTP 接口
"""

import sys
import os
# 添加 DARE Framework 根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "Deterministic-Agent-Runtime-Engine-main"))

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from dare_framework.agent.builder import DareAgentBuilder
from dare_framework.model.adapters.openrouter_adapter import OpenRouterModelAdapter
from dare_framework.tool import ToolResult, RiskLevelName
from dare_framework.tool.kernel import IToolGateway, ITool
from dare_framework.tool.types import RunContext, ToolType, CapabilityKind
from dare_framework.skill._internal.filesystem_skill_loader import FileSystemSkillLoader
from dare_framework.skill._internal.skill_store import SkillStore
from dare_framework.skill._internal.search_skill_tool import SearchSkillTool
from dare_framework.mcp.loader import load_mcp_configs
from dare_framework.mcp.factory import create_mcp_clients
from dare_framework.mcp.tool_provider import McpToolManager
from dare_framework.memory import InMemorySTM, create_long_term_memory
from dare_framework.plan._internal.default_planner import DefaultPlanner
from dare_framework.plan._internal.default_remediator import DefaultRemediator
from dare_framework.context import Message, MessageKind, MessageRole


# ========== 1. 自定义工具：获取当前时间 ==========
class GetCurrentTimeTool(ITool):
    """获取当前时间的工具"""
    
    @property
    def id(self) -> str:
        return "get_current_time"
    
    @property
    def name(self) -> str:
        return "get_current_time"
    
    @property
    def description(self) -> str:
        return "获取当前的系统时间，支持指定时区"
    
    @property
    def risk_level(self) -> RiskLevelName:
        return "read_only"  # 只读操作，风险最低
    
    @property
    def tool_type(self) -> ToolType:
        return ToolType.ATOMIC  # 单次执行工具
    
    @property
    def capability_kind(self) -> CapabilityKind:
        return CapabilityKind.TOOL
    
    @property
    def is_work_unit(self) -> bool:
        return False  # 不是工作单元循环
    
    @property
    def requires_approval(self) -> bool:
        return False  # 不需要审批
    
    @property
    def timeout_seconds(self) -> int:
        return 10  # 10秒超时
    
    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "时区，例如: Asia/Shanghai, UTC",
                    "default": "Asia/Shanghai"
                }
            },
            "required": []
        }
    
    async def execute(self, *, run_context: RunContext[Any], timezone: str = "Asia/Shanghai") -> ToolResult:
        try:
            if timezone == "UTC":
                dt = datetime.now(timezone.utc)
            else:
                from pytz import timezone as pytz_timezone
                dt = datetime.now(pytz_timezone(timezone))
            
            datetime_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            result = {
                "datetime": datetime_str,
                "timestamp": int(dt.timestamp()),
                "timezone": timezone,
                "isoformat": dt.isoformat(),
                "content": f"当前时间: {datetime_str} ({timezone})"
            }
            
            return ToolResult[Dict[str, Any]](
                success=True,
                output=result,
                error=None
            )
        except Exception as e:
            return ToolResult[Dict[str, Any]](
                success=False,
                output={},
                error=str(e)
            )


# ========== 扩展工具1：获取系统信息 ==========
class GetSystemInfoTool(ITool):
    """获取当前系统信息工具"""
    
    @property
    def id(self) -> str:
        return "get_system_info"
    
    @property
    def name(self) -> str:
        return "get_system_info"
    
    @property
    def description(self) -> str:
        return "获取当前运行环境的系统信息，包括操作系统、Python版本、CPU、内存使用情况"
    
    @property
    def risk_level(self) -> RiskLevelName:
        return "read_only"
    
    @property
    def tool_type(self) -> ToolType:
        return ToolType.ATOMIC
    
    @property
    def capability_kind(self) -> CapabilityKind:
        return CapabilityKind.TOOL
    
    @property
    def is_work_unit(self) -> bool:
        return False
    
    @property
    def requires_approval(self) -> bool:
        return False
    
    @property
    def timeout_seconds(self) -> int:
        return 10
    
    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": []
        }
    
    async def execute(self, *, run_context: RunContext[Any]) -> ToolResult:
        try:
            import platform
            import psutil
            import sys
            import os
            
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            result = {
                "os": platform.system(),
                "os_release": platform.release(),
                "python_version": sys.version.split()[0],
                "cpu_count": psutil.cpu_count(),
                "cpu_percent": psutil.cpu_percent(interval=0.5),
                "memory_total_gb": round(mem.total / (1024**3), 2),
                "memory_used_gb": round(mem.used / (1024**3), 2),
                "memory_percent": mem.percent,
                "disk_total_gb": round(disk.total / (1024**3), 2),
                "disk_used_gb": round(disk.used / (1024**3), 2),
                "disk_percent": disk.percent,
                "working_dir": os.getcwd()
            }
            
            return ToolResult[Dict[str, Any]](
                success=True,
                output=result
            )
        except ImportError as e:
            return ToolResult[Dict[str, Any]](
                success=False,
                output={},
                error=f"缺少依赖 psutil，请安装: pip install psutil ({str(e)})"
            )
        except Exception as e:
            return ToolResult[Dict[str, Any]](
                success=False,
                output={},
                error=str(e)
            )


# ========== 扩展工具2：计算日期差 ==========
class CalculateDateDiffTool(ITool):
    """计算两个日期之间的天数差"""
    
    @property
    def id(self) -> str:
        return "calculate_date_diff"
    
    @property
    def name(self) -> str:
        return "calculate_date_diff"
    
    @property
    def description(self) -> str:
        return "计算两个日期之间相差多少天，格式为 YYYY-MM-DD"
    
    @property
    def risk_level(self) -> RiskLevelName:
        return "read_only"
    
    @property
    def tool_type(self) -> ToolType:
        return ToolType.ATOMIC
    
    @property
    def capability_kind(self) -> CapabilityKind:
        return CapabilityKind.TOOL
    
    @property
    def is_work_unit(self) -> bool:
        return False
    
    @property
    def requires_approval(self) -> bool:
        return False
    
    @property
    def timeout_seconds(self) -> int:
        return 10
    
    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "date1": {
                    "type": "string",
                    "description": "第一个日期，格式 YYYY-MM-DD"
                },
                "date2": {
                    "type": "string",
                    "description": "第二个日期，格式 YYYY-MM-DD"
                }
            },
            "required": ["date1", "date2"]
        }
    
    async def execute(self, *, run_context: RunContext[Any], date1: str, date2: str) -> ToolResult:
        try:
            from datetime import datetime
            
            d1 = datetime.strptime(date1, "%Y-%m-%d").date()
            d2 = datetime.strptime(date2, "%Y-%m-%d").date()
            delta = abs(d2 - d1)
            
            result = {
                "date1": date1,
                "date2": date2,
                "days_diff": delta.days,
                "description": f"{date1} 和 {date2} 相差 {delta.days} 天"
            }
            
            return ToolResult[Dict[str, Any]](
                success=True,
                output=result
            )
        except ValueError as e:
            return ToolResult[Dict[str, Any]](
                success=False,
                output={},
                error=f"日期格式错误，请使用 YYYY-MM-DD 格式: {str(e)}"
            )
        except Exception as e:
            return ToolResult[Dict[str, Any]](
                success=False,
                output={},
                error=str(e)
            )


# ========== 2. 服务配置 ==========
class AgentConfig:
    """Agent 配置，从环境变量读取"""
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "z-ai/glm-4.7")
    OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    SKILL_PATHS: List[str] = os.getenv("SKILL_PATHS", "./skills").split(",")
    MCP_CONFIG_PATHS: List[str] = os.getenv("MCP_CONFIG_PATHS", "./.dare/mcp").split(",")
    PORT: int = int(os.getenv("PORT", "8000"))
    HOST: str = os.getenv("HOST", "0.0.0.0")


# ========== 3. 全局 Agent 管理 ==========
class ManagedAgent:
    """可动态扩展的 Managed Agent"""
    
    def __init__(self):
        self.agent = None
        self.skill_store = None
        self.mcp_clients: List = []
        self.initialized = False
    
    async def initialize(self):
        """初始化 Agent"""
        if self.initialized:
            return
        
        print("Initializing DARE Time Agent...")
        
        # 1. 初始化模型
        if not AgentConfig.OPENROUTER_API_KEY:
            raise ValueError("OPENROUTER_API_KEY environment variable is required")
        
        model = OpenRouterModelAdapter(
            api_key=AgentConfig.OPENROUTER_API_KEY,
            model=AgentConfig.OPENROUTER_MODEL,
            base_url=AgentConfig.OPENROUTER_BASE_URL
        )
        
        # 2. 初始化记忆
        stm = InMemorySTM()  # 短内存直接实例化
        
        # 长期记忆 - 支持语义检索，如果没有 embedding 模型也可以继续使用 rawdata
        # 如果需要向量检索，请确保安装了 sentence-transformers 并配置 embedding_adapter
        try:
            from dare_framework.model.adapters.openai_embedding_adapter import OpenAIEmbeddingAdapter
            # 使用同一个 API 端点提供 embedding 服务
            embedding_adapter = OpenAIEmbeddingAdapter(
                api_key=AgentConfig.OPENROUTER_API_KEY,
                base_url=AgentConfig.OPENROUTER_BASE_URL,
                model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
            )
            # 向量长期记忆，持久化存储到本地
            ltm = create_long_term_memory({
                "type": "vector",
                "storage": "chromadb",
                "collection_name": "dare_time_agent_memory",
                "persist_directory": "./.ltm_data"
            }, embedding_adapter)
            print("Long-term vector memory initialized")
        except Exception as e:
            # 如果无法初始化向量存储，回退到简单的 rawdata 存储
            print(f"Vector memory init failed ({e}), falling back to rawdata in-memory storage")
            ltm = create_long_term_memory({
                "type": "rawdata",
                "storage": "in_memory"
            }, None)
        
        # 3. 加载 Skills
        if any(os.path.exists(p.strip()) for p in AgentConfig.SKILL_PATHS):
            loader = FileSystemSkillLoader()
            loaders = [loader]
            self.skill_store = SkillStore(loaders)
            all_skills = self.skill_store.list_skills()
            print(f"Loaded {len(all_skills)} skills")
        else:
            self.skill_store = SkillStore([])
            print("No skill paths found, skill store is empty")
        
        # 4. 加载 MCP
        mcp_provider = None
        if any(os.path.exists(p.strip()) for p in AgentConfig.MCP_CONFIG_PATHS):
            configs = load_mcp_configs(
                AgentConfig.MCP_CONFIG_PATHS,
                workspace_dir=".",
                user_dir=os.path.expanduser("~")
            )
            self.mcp_clients = create_mcp_clients(configs, connect=True, skip_errors=True)
            mcp_provider = McpToolManager(self.mcp_clients)
            print(f"Connected {len(self.mcp_clients)} MCP servers")
        
        # 5. 构建 Agent
        # 获取默认系统提示词并添加自定义指令
        from dare_framework.plan._internal.default_planner import DEFAULT_PLAN_SYSTEM_PROMPT
        
        # 添加自定义提示词，明确告知可用工具
        custom_system_prompt = DEFAULT_PLAN_SYSTEM_PROMPT + """

额外任务说明：
你是一个提供时间相关服务的助手。

关于工具使用：
- 当用户询问**当前时间、现在几点**时，**必须**使用 get_current_time 工具获取准确的当前时间，不要凭自己的知识直接回答
- 当用户询问两个日期相差多少天，**必须**使用 calculate_date_diff 工具计算
- 当用户询问系统信息、服务器状态，使用 get_system_info 工具
- 当用户问时间相关的知识问题，使用 search_skill 检索技能库中的常见问题
- 当用户要求记住某些信息，使用 knowledge_add 存储到长期记忆
- 当回答需要背景知识，使用 knowledge_get 从长期记忆中检索

工具能力说明：
- get_current_time: 获取当前系统的准确时间，支持时区参数，默认时区为 Asia/Shanghai
- calculate_date_diff: 计算两个日期之间相差多少天
- get_system_info: 获取系统信息（操作系统、CPU、内存、磁盘）
- search_skill: 在技能库中搜索相关知识
- knowledge_add: 添加信息到长期记忆
- knowledge_get: 从长期记忆检索信息
"""
        
        # 配置规划器和修复器
        planner = DefaultPlanner(
            model,
            system_prompt=custom_system_prompt
        )
        remediator = DefaultRemediator(model)
        
        # 添加所有自定义工具
        from dare_framework.knowledge._internal.knowledge_tools import KnowledgeAddTool, KnowledgeGetTool
        
        builder = DareAgentBuilder("time-service-agent")\
            .with_model(model)\
            .with_short_term_memory(stm)\
            .with_long_term_memory(ltm)\
            .add_tools(GetCurrentTimeTool())\
            .add_tools(GetSystemInfoTool())\
            .add_tools(CalculateDateDiffTool())\
            .add_tools(KnowledgeAddTool(ltm))\
            .add_tools(KnowledgeGetTool(ltm))
        
        # 添加技能检索工具（如果有技能）
        if self.skill_store and len(self.skill_store.list_skills()) > 0:
            builder.add_tools(SearchSkillTool(self.skill_store))
        
        # 添加 MCP 工具（如果有）
        if mcp_provider:
            builder.add_tool_provider(mcp_provider)
        
        # 配置规划器和修复器
        agent = await builder\
            .with_planner(planner)\
            .with_remediator(remediator)\
            .build()
        
        self.agent = agent
        self.initialized = True
        print("DARE Time Agent initialized successfully!")
    
    async def shutdown(self):
        """关闭资源"""
        for client in self.mcp_clients:
            try:
                await client.disconnect()
            except Exception:
                pass
        self.initialized = False
    
    async def reload_skills(self) -> Dict[str, Any]:
        """动态重新加载 Skills"""
        # SkillStore 原生自带 reload 方法，直接调用重新从文件系统加载
        self.skill_store.reload()
        all_skills = self.skill_store.list_skills()
        
        # 需要更新 Agent 中的 SearchSkillTool，因为它持有旧的 skill_store 引用
        if self.agent and self.skill_store:
            # 移除旧的 SearchSkillTool 工具
            self.agent.tool_registry.tools = [
                t for t in self.agent.tool_registry.tools 
                if t.id != "search_skill"
            ]
            # 添加新的 SearchSkillTool，使用更新后的 skill_store
            from dare_framework.skill._internal.search_skill_tool import SearchSkillTool
            self.agent.tool_registry.add_tool(SearchSkillTool(self.skill_store))
        
        return {
            "status": "ok",
            "loaded_skills": len(all_skills),
            "skill_list": [s.name for s in all_skills]
        }
    
    async def reload_mcp(self) -> Dict[str, Any]:
        """动态重新加载 MCP 配置"""
        # 断开旧连接
        for client in self.mcp_clients:
            try:
                await client.disconnect()
            except Exception:
                pass
        
        # 重新加载
        configs = load_mcp_configs(
            AgentConfig.MCP_CONFIG_PATHS,
            workspace_dir=".",
            user_dir=os.path.expanduser("~")
        )
        self.mcp_clients = create_mcp_clients(configs, connect=True, skip_errors=True)
        
        return {
            "status": "ok",
            "connected_servers": len(self.mcp_clients),
            "servers": [c.config.name for c in self.mcp_clients]
        }
    
    async def run_query(self, question: str) -> Dict[str, Any]:
        """执行查询"""
        if not self.initialized or not self.agent:
            raise HTTPException(status_code=503, detail="Agent not initialized")
        
        try:
            # 将字符串转换为 Message 对象
            message = Message(
                role=MessageRole.USER,
                kind=MessageKind.CHAT,
                text=question
            )
            result = await self.agent.execute(message)
            print(f"DEBUG: result type={type(result)}, result={result}")
            
            # 如果返回的是字符串，包装成标准格式
            if isinstance(result, str):
                return {
                    "success": True,
                    "answer": result,
                    "output": None,
                    "errors": [],
                    "metadata": {}
                }
            
            # 如果是 RunResult 对象，正常提取字段
            return {
                "success": getattr(result, 'success', False),
                "answer": getattr(result, 'output_text', None),
                "output": getattr(result, 'output', None),
                "errors": getattr(result, 'errors', []),
                "metadata": getattr(result, 'metadata', {})
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))


# ========== 4. FastAPI 服务 ==========
managed_agent = ManagedAgent()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化
    await managed_agent.initialize()
    yield
    # 关闭时清理
    await managed_agent.shutdown()

app = FastAPI(
    title="DARE Time Agent Service",
    description="基于 DARE Framework 的服务化 Agent 示例，支持动态加载 Skill 和 MCP",
    version="1.0.0",
    lifespan=lifespan
)


# ========== 5. API 模型 ==========
class QueryRequest(BaseModel):
    question: str

class QueryResponse(BaseModel):
    success: bool
    answer: Optional[str]
    output: Optional[Dict[str, Any]]
    errors: Optional[List[str]]
    metadata: Optional[Dict[str, Any]]

class ReloadResponse(BaseModel):
    status: str
    loaded_skills: Optional[int]
    skill_list: Optional[List[str]]
    connected_servers: Optional[int]
    servers: Optional[List[str]]


# ========== 6. API 端点 ==========
@app.post("/query", response_model=QueryResponse, tags=["Agent"])
async def query(request: QueryRequest):
    """
    向 Agent 发送查询
    """
    result = await managed_agent.run_query(request.question)
    return result


@app.post("/skills/reload", response_model=ReloadResponse, tags=["Management"])
async def reload_skills():
    """
    动态重新加载所有 Skills
    当你上传了新的 Skill 到技能目录后，调用这个接口生效
    """
    result = await managed_agent.reload_skills()
    return result


@app.post("/mcp/reload", response_model=ReloadResponse, tags=["Management"])
async def reload_mcp():
    """
    动态重新加载所有 MCP 配置
    当你添加了新的 MCP 服务配置后，调用这个接口生效
    """
    result = await managed_agent.reload_mcp()
    return result


@app.get("/status", tags=["Management"])
async def status():
    """
    获取服务状态
    """
    return {
        "status": "running" if managed_agent.initialized else "initializing",
        "agent_name": "time-service-agent",
        "skills_count": len(managed_agent.skill_store.list_skills()) if managed_agent.skill_store else 0,
        "mcp_connected": len(managed_agent.mcp_clients)
    }


# ========== 7. 启动服务 ==========
if __name__ == "__main__":
    # 检查依赖
    try:
        import fastapi
        import uvicorn
    except ImportError:
        print("Error: fastapi and uvicorn are required. Install with:")
        print("  pip install fastapi uvicorn python-multipart pytz")
        exit(1)
    
    uvicorn.run(
        "dare-time-agent-demo:app",
        host=AgentConfig.HOST,
        port=AgentConfig.PORT,
        reload=True,  # 开发模式，生产环境请关闭
        workers=1
    )
