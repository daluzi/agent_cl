# DARE 服务化 Agent Demo

这是一个基于 DARE Framework 的服务化 Agent 示例，提供：

1. 基础的查询当前时间能力
2. 服务化部署，暴露 HTTP 接口
3. 支持动态上传 Skill，无需重启服务即可加载
4. 支持动态添加 MCP 配置，无需重启即可生效

## 快速开始

### 1. 安装依赖

```bash
# 安装框架（假设你已经下载了 DARE 源码）
python -m pip install -e /path/to/Deterministic-Agent-Runtime-Engine

# 安装 web 服务依赖
pip install fastapi uvicorn python-multipart pytz
```

### 2. 配置环境变量

```bash
# 必填：你的 OpenRouter API Key
export OPENROUTER_API_KEY="your-openrouter-api-key"

# 可选：指定模型，默认 z-ai/glm-4.7
export OPENROUTER_MODEL="openai/gpt-4o"

# 可选：服务端口，默认 8000
export PORT=8000

# 可选：Skill 目录，多个用逗号分隔
export SKILL_PATHS="./skills"

# 可选：MCP 配置目录，多个用逗号分隔
export MCP_CONFIG_PATHS="./.dare/mcp"
```

### 3. 运行服务

```bash
python dare-time-agent-demo.py
```

服务启动后，你可以访问 http://localhost:8000/docs 查看 API 文档并测试。

## API 接口

| 接口             | 方法 | 说明                      |
| ---------------- | ---- | ------------------------- |
| `/query`         | POST | 向 Agent 发送查询         |
| `/skills/reload` | POST | 动态重新加载所有 Skills   |
| `/mcp/reload`    | POST | 动态重新加载所有 MCP 配置 |
| `/status`        | GET  | 获取服务状态              |

## 使用示例

### 1. 查询时间

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "现在几点了？"}'
```

响应示例：

```json
{
  "success": true,
  "answer": "当前时间是 2026-03-25 17:46:00 (Asia/Shanghai)",
  "output": {
    "content": "...",
    "metadata": {}
  }
}
```

### 2. 动态添加 Skill

1. 在 `./skills` 目录下创建你的 Skill：

```
./skills/
  my-custom-skill/
    SKILL.md
```

2. 在 `SKILL.md` 中编写你的技能说明

3. 调用重载接口：

```bash
curl -X POST http://localhost:8000/skills/reload
```

无需重启服务，新 Skill 就可以被 Agent 使用了。

### 3. 动态添加 MCP

1. 在 `./.dare/mcp` 目录下添加 MCP 配置文件（json/yaml）：

```json
{
  "mcpServers": {
    "my-mcp-server": {
      "transport": "stdio",
      "command": "node",
      "args": ["/path/to/mcp-server/index.js"],
      "env": {}
    }
  }
}
```

2. 调用重载接口：

```bash
curl -X POST http://localhost:8000/mcp/reload
```

MCP 服务的所有工具会自动注册到 Agent 中，立即可用。

## 项目结构

```
.
├── dare-time-agent-demo.py   # 主程序
├── skills/                   # 你的 Skills（动态加载）
│   └── ...
└── .dare/
    └── mcp/                  # MCP 配置（动态加载）
        └── ...
```

## 部署到云端

这个 Demo 本身就是为云端部署设计的，可以直接部署到：

- **Docker**：可以很容易编写 Dockerfile 容器化
- **Kubernetes**：支持水平扩展（注意每个实例会加载自己的 Skill/MCP）
- **Serverless**：适配好冷启动即可
- **传统 VPS**：直接运行即可，推荐使用 systemd 管理

## 主要设计特点

1. **遵从 DARE 设计原则**：LLM 不可信、外部可验证、状态外化、可审计
2. **完全可插拔**：Skill/MCP 都支持动态更新，不影响服务运行
3. **标准 HTTP 接口**：易于被其他服务调用
4. **开箱即用**：只需要配置 API Key 就能运行
