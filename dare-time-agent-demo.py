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
            
            result = {
                "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
                "timestamp": int(dt.timestamp()),
                "timezone": timezone,
                "isoformat": dt.isoformat()
            }
            
            return ToolResult[Dict[str, Any]](
                success=True,
                output=result,
                content=f"当前时间: {result['datetime']} ({timezone})"
            )
        except Exception as e:
            return ToolResult[Dict[str, Any]](
                success=False,
                output={},
                error=str(e),
                content=f"获取时间失败: {str(e)}"
            )


# ========== 2. 服务配置 ==========
class AgentConfig:
    """Agent 配置，从环境变量读取"""
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "z-ai/glm-4.7")
    OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
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
        ltm = create_long_term_memory({
            "type": "rawdata",
            "storage": "in_memory"
        }, None)  # 不需要 embedding，使用 rawdata 类型
        
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
        # 添加自定义系统提示词，明确告知可用工具
        custom_instructions = """
你是一个提供时间查询服务的助手。当用户询问当前时间、日期时，**必须**使用 get_current_time 工具来获取准确的当前时间，不要凭自己的知识回答。

工具能力说明：
- get_current_time: 获取当前系统的准确时间，支持时区参数，默认时区为 Asia/Shanghai
"""
        
        from dare_framework.model.types import Prompt
        # 创建自定义提示词
        custom_prompt = Prompt(
            id="custom_system",
            text=custom_instructions
        )
        
        builder = DareAgentBuilder("time-service-agent")\
            .with_model(model)\
            .with_short_term_memory(stm)\
            .with_long_term_memory(ltm)\
            .add_tools(GetCurrentTimeTool())\
            .with_prompt(custom_prompt)
        
        # 添加技能检索工具（如果有技能）
        if self.skill_store and len(self.skill_store.list_skills()) > 0:
            builder.add_tools(SearchSkillTool(self.skill_store))
        
        # 添加 MCP 工具（如果有）
        if mcp_provider:
            builder.add_tool_provider(mcp_provider)
        
        # 配置规划器和修复器
        agent = await builder\
            .with_planner(DefaultPlanner(model))\
            .with_remediator(DefaultRemediator(model))\
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
        loader = FileSystemSkillLoader()
        self.skill_store = SkillStore([loader])
        all_skills = self.skill_store.list_skills()
        
        # 重新构建 Agent（这里简化处理，实际生产中可以更优雅）
        # 因为工具已经注册，只需要更新 skill store
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
