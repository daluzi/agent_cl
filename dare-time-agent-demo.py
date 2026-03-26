"""
DARE Framework 服务化 Agent Demo
功能：
1. 提供查询当前时间的基础能力
2. 支持动态加载 Skill 和 MCP
3. 服务化部署，暴露 HTTP 接口
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from dare_framework.agent import DareAgentBuilder
from dare_framework.model import OpenRouterModelAdapter
from dare_framework.tool import IToolGateway, ToolResult, RiskLevelName
from dare_framework.core.tool import ITool
from dare_framework.core.context import ExecutionContext
from dare_framework.skill import FileSystemSkillLoader, SkillStore, SearchSkillTool
from dare_framework.mcp import load_mcp_configs, create_mcp_clients, MCPToolProvider
from dare_framework.memory import create_short_term_memory, create_long_term_memory
from dare_framework.planner import DefaultPlanner
from dare_framework.remediator import DefaultRemediator


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
    
    async def invoke(self, input_params: Dict[str, Any], context: ExecutionContext) -> ToolResult:
        try:
            tz_name = input_params.get("timezone", "Asia/Shanghai")
            if tz_name == "UTC":
                dt = datetime.now(timezone.utc)
            else:
                from pytz import timezone as pytz_timezone
                dt = datetime.now(pytz_timezone(tz_name))
            
            result = {
                "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
                "timestamp": int(dt.timestamp()),
                "timezone": tz_name,
                "isoformat": dt.isoformat()
            }
            
            return ToolResult(
                success=True,
                content=f"当前时间: {result['datetime']} ({tz_name})",
                metadata=result
            )
        except Exception as e:
            return ToolResult(
                success=False,
                content=f"获取时间失败: {str(e)}",
                error=str(e)
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
        stm = create_short_term_memory()
        ltm = create_long_term_memory({
            "type": "vector",
            "storage": "in_memory"
        }, None)  # embedding 可选，这里简化处理
        
        # 3. 加载 Skills
        self.skill_store = SkillStore()
        if any(os.path.exists(p.strip()) for p in AgentConfig.SKILL_PATHS):
            loader = FileSystemSkillLoader()
            all_skills = []
            for path in AgentConfig.SKILL_PATHS:
                path = path.strip()
                if os.path.exists(path):
                    skills = loader.load([path])
                    all_skills.extend(skills)
            self.skill_store.add_skills(all_skills)
            print(f"Loaded {len(all_skills)} skills")
        
        # 4. 加载 MCP
        mcp_provider = None
        if any(os.path.exists(p.strip()) for p in AgentConfig.MCP_CONFIG_PATHS):
            configs = load_mcp_configs(
                AgentConfig.MCP_CONFIG_PATHS,
                workspace_dir=".",
                user_dir=os.path.expanduser("~")
            )
            self.mcp_clients = create_mcp_clients(configs, connect=True, skip_errors=True)
            mcp_provider = MCPToolProvider(self.mcp_clients)
            print(f"Connected {len(self.mcp_clients)} MCP servers")
        
        # 5. 构建 Agent
        builder = DareAgentBuilder("time-service-agent")\
            .with_model(model)\
            .with_short_term_memory(stm)\
            .with_long_term_memory(ltm)\
            .add_tools(GetCurrentTimeTool())
        
        # 添加技能检索工具（如果有技能）
        if self.skill_store and len(self.skill_store.list_skills()) > 0:
            builder.add_tools(SearchSkillTool(self.skill_store))
        
        # 添加 MCP 工具（如果有）
        if mcp_provider:
            builder.add_tool_provider(mcp_provider)
        
        # 配置规划器和修复器
        agent = builder\
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
        all_skills = []
        for path in AgentConfig.SKILL_PATHS:
            path = path.strip()
            if os.path.exists(path):
                skills = loader.load([path])
                all_skills.extend(skills)
        
        self.skill_store = SkillStore()
        self.skill_store.add_skills(all_skills)
        
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
            result = await self.agent.run(question)
            
            return {
                "success": result.success,
                "answer": result.output_text,
                "output": result.output,
                "errors": result.errors,
                "metadata": result.metadata
            }
        except Exception as e:
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
