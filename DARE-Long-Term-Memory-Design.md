# DARE 长期记忆服务（DARE-LTM）完整设计文档

## 目录

1. [概述](#1-概述)
2. [架构设计](#2-架构设计)
3. [数据模型设计](#3-数据模型设计)
4. [API 接口设计](#4-api-接口设计)
5. [Gauss 表格设计](#5-gauss-表格设计)
6. [Elasticsearch 集成设计](#6-elasticsearch-集成设计)
7. [内部核心逻辑设计](#7-内部核心逻辑设计)
8. [部署架构](#8-部署架构)
9. [数据生命周期管理](#9-数据生命周期管理)
10. [安全与权限设计](#10-安全与权限设计)
11. [性能优化策略](#11-性能优化策略)
12. [监控与运维](#12-监控与运维)

---

## 1. 概述

### 1.1 项目背景

DARE (Deterministic Agent Runtime Engine) 框架需要一个独立的长期记忆服务，用于存储 Agent 运行过程中的知识、对话历史、经验总结等信息，支持语义检索、精确查询和增量更新。该服务需要独立部署，独立提供服务，供多个 Agent 实例共享使用。

### 1.2 设计目标

- **独立部署**：作为独立微服务部署，不依赖 DARE 主框架
- **多租户支持**：支持多个 Agent/用户实例隔离使用
- **混合检索**：支持向量语义检索 + 关键词全文检索 + 结构化过滤
- **可扩展**：支持水平扩展，应对大规模数据存储和检索
- **高可用**：服务高可用设计，数据持久化保证
- **易维护**：完整的监控、日志、备份恢复机制

### 1.3 核心功能

| 功能模块 | 功能描述 |
|---------|---------|
| 知识存储 | 支持存储文本、结构化数据、对话片段等多种记忆类型 |
| 向量化 | 集成 Embedding 模型，自动生成向量表示 |
| 混合检索 | 语义相似度 + 关键词 + 元条件过滤复合查询 |
| 记忆管理 | CRUD、过期清理、版本管理、标签分类 |
| 统计分析 | 访问统计、热度分析、质量评估 |
| 批量操作 | 批量导入导出、批量删除 |

---

## 2. 架构设计

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Client (Agents / Applications)                    │
└─────────────────────────────┬────────────────────────────────────────────┘
                              │ HTTP/gRPC
                              ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                        API Gateway / Load Balancer                       │
└─────────────────────────────┬────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                     DARE-LTM Service (Stateless)                         │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────┐  │
│  │ API Handler │ │ Memory Core │ │ Embedding   │ │ Query Processor │  │
│  │             │ │             │ │  Adapter    │ │                 │  │
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────────┘  │
└─────────────────────────────┬────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ↓                   ↓                   ↓
    ┌───────────┐      ┌───────────┐      ┌───────────────┐
    │  GaussDB  │      │ Elasticsearch  │ │  Vector DB    │
    │ (Relational)  │  │ (Full-text)      │ │(Chroma/Pgvec)│
    └─────────────┘      └─────────────┘      └───────────────┘
```

### 2.2 分层架构

**1. API 层**
- RESTful API + 可选 gRPC
- 认证鉴权
- 请求限流
- 参数校验

**2. 业务逻辑层**
- 记忆核心管理
- 查询处理器
- 向量化适配器
- 缓存管理器

**3. 数据访问层**
- GaussDB 访问层（结构化数据、元数据）
- Elasticsearch 访问层（全文检索）
- 向量数据库访问层（语义检索）

**4. 存储层**
- 元数据存储：GaussDB (PostgreSQL 兼容)
- 全文检索：Elasticsearch
- 向量存储：可选 Chroma / Pgvector on GaussDB

### 2.3 设计原则

- **读写分离**：读请求走缓存和 ES，写请求先走数据库再异步同步
- **最终一致性**：三大存储之间通过异步任务保证一致
- **水平扩展**：服务无状态，可动态扩容
- **容错设计**：单存储故障不影响整体服务可用性

---

## 3. 数据模型设计

### 3.1 记忆类型枚举

```python
class MemoryType(Enum):
    KNOWLEDGE = "knowledge"           # 静态知识
    CONVERSATION = "conversation"     # 对话片段
    SUMMARY = "summary"               # 经验总结
    TASK = "task"                     # 任务记录
    REFLECTION = "reflection"         # 反思笔记
    OBSERVATION = "observation"       # 观察记录
```

### 3.2 记忆可见性枚举

```python
class Visibility(Enum):
    PRIVATE = "private"     # 仅自己可见
    TEAM = "team"           # 团队共享
    PUBLIC = "public"       # 公开
```

### 3.3 核心记忆实体

```python
@dataclass
class Memory:
    # 唯一标识
    id: str                          # UUID 主键
    tenant_id: str                   # 租户/Agent ID
    user_id: Optional[str]           # 所属用户 ID
    
    # 内容
    content: str                     # 记忆正文内容
    summary: Optional[str]           # 摘要，用于快速预览
    content_type: str                # text/markdown/json
    
    # 分类
    memory_type: MemoryType          # 记忆类型
    tags: List[str]                  # 标签列表
    collection: Optional[str]        # 合集名称
    
    # 向量
    embedding: Optional[List[float]] # 向量嵌入（可选，也可存在向量库）
    embedding_model: Optional[str]   # 使用的 embedding 模型
    
    # 元数据
    metadata: Dict[str, Any]         # 扩展元数据 JSON
    source: Optional[str]            # 来源（哪个 Agent / 技能）
    
    # 可见性
    visibility: Visibility
    
    # 时间
    created_at: datetime             # 创建时间
    updated_at: datetime             # 更新时间
    accessed_at: Optional[datetime]  # 最后访问时间
    
    # 统计
    access_count: int                # 访问次数
    score: float                     # 质量评分（0-1），用于排序
    
    # 软删除
    is_deleted: bool
    deleted_at: Optional[datetime]
```

---

## 4. Gauss 表格设计

GaussDB 基于 PostgreSQL，兼容 PostgreSQL 语法。我们用它存储所有记忆的元数据和结构化信息。

### 4.1 核心表设计

#### 4.1.1 tenants 租户表

```sql
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    quota_bytes BIGINT DEFAULT 10737418240, -- 默认 10GB
    used_bytes BIGINT DEFAULT 0,
    max_memories INTEGER DEFAULT 100000,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT quota_check CHECK (used_bytes <= quota_bytes)
);

CREATE INDEX idx_tenants_is_active ON tenants(is_active);
```

#### 4.1.2 memories 记忆表

```sql
CREATE TABLE memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID,
    
    content TEXT NOT NULL,
    summary VARCHAR(1000),
    content_type VARCHAR(20) DEFAULT 'text',
    
    memory_type VARCHAR(30) NOT NULL,
    tags TEXT[], -- 数组类型存储标签
    collection_name VARCHAR(100),
    
    embedding_model VARCHAR(100),
    -- 如果使用 pgvector，启用这一行：
    -- embedding vector(1536),
    
    metadata JSONB,
    source VARCHAR(255),
    visibility VARCHAR(20) DEFAULT 'private',
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    accessed_at TIMESTAMP WITH TIME ZONE,
    
    access_count INTEGER DEFAULT 0,
    score DOUBLE PRECISION DEFAULT 1.0,
    
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP WITH TIME ZONE,
    
    -- 全文搜索分词向量（PostgreSQL 内置全文检索）
    search_vector TSVECTOR
);

-- 索引设计
CREATE INDEX idx_memories_tenant_id ON memories(tenant_id);
CREATE INDEX idx_memories_user_id ON memories(user_id);
CREATE INDEX idx_memories_memory_type ON memories(memory_type);
CREATE INDEX idx_memories_collection ON memories(tenant_id, collection_name);
CREATE INDEX idx_memories_tags ON memories USING GIN(tags);
CREATE INDEX idx_memories_metadata ON memories USING GIN(metadata);
CREATE INDEX idx_memories_is_deleted ON memories(is_deleted);
CREATE INDEX idx_memories_created_at ON memories(created_at DESC);
CREATE INDEX idx_memories_score ON memories(score DESC);
-- 全文检索索引
CREATE INDEX idx_memories_search_vector ON memories USING GIN(search_vector);

-- 触发器：自动更新 search_vector
CREATE FUNCTION memories_update_search_vector() RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector = 
        setweight(to_tsvector('english', COALESCE(NEW.summary, '')), 'A') || 
        setweight(to_tsvector('english', NEW.content), 'B');
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_memories_update_search_vector
    BEFORE INSERT OR UPDATE ON memories
    FOR EACH ROW
    EXECUTE FUNCTION memories_update_search_vector();
```

#### 4.1.3 collections 合集表

```sql
CREATE TABLE collections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(tenant_id, name)
);

CREATE INDEX idx_collections_tenant_id ON collections(tenant_id);
```

#### 4.1.4 access_log 访问日志表

```sql
CREATE TABLE access_log (
    id BIGSERIAL PRIMARY KEY,
    memory_id UUID NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    user_id UUID,
    action VARCHAR(20) NOT NULL, -- create/update/delete/query/view
    query_text TEXT,
    response_time_ms INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_access_log_tenant ON access_log(tenant_id, created_at);
CREATE INDEX idx_access_log_memory ON access_log(memory_id);
```

### 4.2 如果使用 Pgvector 扩展存储向量

如果选择把向量直接存在 GaussDB 中，可以启用 `embedding` 列：

```sql
-- 先启用扩展
CREATE EXTENSION IF NOT EXISTS vector;

-- 修改表添加向量列
ALTER TABLE memories ADD COLUMN embedding vector(1536);

-- 创建向量索引（IVFFlat 索引适合 100k+ 数据量）
CREATE INDEX idx_memories_embedding ON memories 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

这样就不需要单独的 Chroma 向量数据库了，架构更简洁。

---

## 5. API 接口设计

### 5.1 认证方式

所有请求需要在 Header 中携带：

```
Authorization: Bearer <api-key>
X-Tenant-ID: <tenant-uuid>
```

### 5.2 错误响应格式

```json
{
  "success": false,
  "error": {
    "code": "NOT_FOUND",
    "message": "Memory not found",
    "details": {}
  }
}
```

### 5.3 成功响应格式

```json
{
  "success": true,
  "data": {},
  "meta": {
    "request_id": "uuid",
    "took_ms": 123
  }
}
```

### 5.4 接口列表

#### 5.4.1 创建记忆

**POST /api/v1/memories**

Request Body:

```json
{
  "content": "这里是记忆的正文内容",
  "summary": "简要摘要",
  "content_type": "text",
  "memory_type": "knowledge",
  "tags": ["AI", "检索"],
  "collection": "my-collection",
  "metadata": {
    "source": "chat-123",
    "author": "agent-1"
  },
  "visibility": "private",
  "user_id": "uuid-xxx",
  "generate_embedding": true
}
```

Response:

```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "created_at": "2026-03-30T10:00:00Z",
    "embedding_generated": true
  }
}
```

---

#### 5.4.2 获取记忆详情

**GET /api/v1/memories/{id}**

Response: 返回完整 Memory 对象

---

#### 5.4.3 更新记忆

**PUT /api/v1/memories/{id}**

Request Body: 同创建，只需要传要更新的字段

自动更新 `updated_at`，如果内容变了自动重新生成 embedding

---

#### 5.4.4 删除记忆

**DELETE /api/v1/memories/{id}**

支持软删除，实际标记 `is_deleted = true`

---

#### 5.4.5 批量创建记忆

**POST /api/v1/memories/batch**

```json
{
  "memories": [
    { /* 同单个创建 */ }
  ],
  "generate_embedding": true
}
```

---

#### 5.4.6 混合检索接口

**POST /api/v1/search**

这是最核心的检索接口，支持向量语义 + 关键词 + 结构化过滤混合查询。

Request Body:

```json
{
  "query": "查询文本，用于生成 embedding 做语义检索",
  "keywords": "可选关键词，用于全文检索",
  "memory_type": "knowledge",
  "tags": ["AI"],
  "collection": "my-collection",
  "user_id": "uuid",
  "filters": {
    "metadata.source": "chat-123",
    "created_at_range": ["2026-01-01", "2026-03-30"]
  },
  "limit": 10,
  "offset": 0,
  "minimum_score": 0.5,
  "include_embedding": false
}
```

查询逻辑：

1. 如果 `query` 不为空，做向量相似度检索，得到 top-k 结果
2. 如果 `keywords` 不为空，做全文关键词检索，得到结果
3. 如果两者都有，取结果交集并做混合排序
4. 应用 `filters` 过滤条件
5. 按 `score * (1 + access_count/1000)` 综合排序
6. 返回分页结果

Response:

```json
{
  "success": true,
  "data": {
    "total": 123,
    "results": [
      {
        "id": "uuid",
        "content": "内容摘要...",
        "memory_type": "knowledge",
        "tags": ["AI"],
        "score": 0.89,
        "similarity_score": 0.85,
        "keyword_score": 0.92,
        "created_at": "2026-03-30T10:00:00Z"
      }
    ]
  },
  "meta": {
    "took_ms": 45
  }
}
```

---

#### 5.4.7 按标签统计

**GET /api/v1/tags**

返回：当前租户下所有标签及其计数

---

#### 5.4.8 列表查询

**GET /api/v1/memories**

参数：

- `memory_type`: 过滤类型
- `collection`: 过滤合集
- `tags`: 过滤标签（逗号分隔）
- `limit` / `offset`: 分页
- `order_by`: created_at / score / accessed_at

---

#### 5.4.9 统计信息

**GET /api/v1/stats**

返回：

```json
{
  "total_memories": 1234,
  "total_bytes": 1234567,
  "by_type": {
    "knowledge": 500,
    "conversation": 700
  },
  "quota_used_percent": 12.3
}
```

---

#### 5.4.10 清理过期数据

**POST /api/v1/admin/cleanup**

```json
{
  "older_than_days": 180,
  "dry_run": true
}
```

需要管理员权限

---

## 6. Elasticsearch 集成设计

### 6.1 为什么需要 Elasticsearch

虽然 PostgreSQL 也支持全文检索，但在以下场景 ES 更优：

1. 大规模数据（百万级以上）下的全文检索性能更好
2. 支持更复杂的分词、高亮、相关度打分
3. 支持中文分词优化（IK 分词器）
4. 聚合统计更灵活

如果数据量在十万级以内，可以只用 PostgreSQL 内置全文检索，省去 ES 维护成本。

### 6.2 ES 索引设计

索引命名：`dare-ltm-{tenant_id}` 或者按租户分 shard，共享一个索引。

推荐：**一个租户一个索引**，隔离性好，便于单独删除/迁移。

### 6.3 Mapping 设计

```json
{
  "mappings": {
    "properties": {
      "id": { "type": "keyword" },
      "tenant_id": { "type": "keyword" },
      "user_id": { "type": "keyword" },
      "content": { 
        "type": "text",
        "analyzer": "ik_max_word",
        "search_analyzer": "ik_smart"
      },
      "summary": { 
        "type": "text",
        "analyzer": "ik_max_word",
        "boost": 2
      },
      "memory_type": { "type": "keyword" },
      "tags": { "type": "keyword" },
      "collection_name": { "type": "keyword" },
      "created_at": { "type": "date" },
      "score": { "type": "float" },
      "metadata": { "type": "object" },
      "is_deleted": { "type": "boolean" }
    }
  },
  "settings": {
    "number_of_shards": 3,
    "number_of_replicas": 1
  }
}
```

说明：

- `summary` 增加 `boost: 2`，让标题匹配更高权重
- 使用 IK 分词器支持中文分词
- `tags`、`memory_type` 使用 `keyword` 类型，便于精确过滤

### 6.4 数据同步流程

```
创建记忆 → 写入 GaussDB 成功 → 异步写入 Elasticsearch → 异步写入向量库
                                       ↓
                              写入失败进入死信队列，重试 → 告警
```

数据同步保证最终一致性，不阻塞写入请求。

### 6.5 ES 查询方式

混合检索时，在 ES 中执行布尔查询：

```json
{
  "query": {
    "bool": {
      "must": [
        { "term": { "tenant_id": "xxx" } },
        { "term": { "is_deleted": false } }
      ],
      "should": [
        { "match": { "content": "keywords" } },
        { "match": { "summary": "keywords" } }
      ],
      "filter": [
        { "term": { "memory_type": "knowledge" } },
        { "terms": { "tags": ["AI"] } }
      ]
    }
  },
  "size": 50
}
```

得到的结果取出 `id` 列表，和向量检索的结果做融合。

---

## 7. 内部核心逻辑设计

### 7.1 创建记忆流程

```
1. 接收请求
2. 参数校验
3. 检查租户配额是否足够
4. 生成 UUID
5. 如果请求生成 embedding：
   a. 调用 embedding adapter 获取向量
   b. 存储向量（到 GaussDB / 向量库）
6. 写入 GaussDB
7. 更新租户已用大小统计
8. 异步同步到 Elasticsearch
9. 返回结果给客户端
```

### 7.2 混合检索流程

```
1. 解析查询参数
2. 并行执行：
   a. 如果有 query 文本 → 生成向量 → 向量库相似度检索，得到 (id, score) 列表
   b. 如果有 keywords → Elasticsearch 全文检索，得到 (id, score) 列表
3. 结果融合：
   - 如果只有一种结果 → 直接使用
   - 如果两种结果 → 基于 id 取交集，混合打分：final_score = α * vector_score + (1-α) * keyword_score
4. 应用结构化过滤条件（在 GaussDB 中查询）
5. 按 final_score * (1 + access_count/1000) 排序
6. 更新 accessed_at 和 access_count（异步）
7. 记录访问日志
8. 返回结果
```

### 7.3 Embedding 适配器设计

采用适配器模式，支持多种 embedding 服务：

```python
class EmbeddingAdapter(ABC):
    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        pass
    
    @abstractmethod
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        pass
```

具体实现：

- `OpenAIEmbeddingAdapter` → 调用 OpenAI / OpenRouter API
- `LocalEmbeddingAdapter` → 调用本地 sentence-transformers 模型
- `OpenCloudEmbeddingAdapter` → 调用火山引擎等云厂商 embedding API

### 7.4 更新记忆流程

- 更新 GaussDB 数据
- 如果内容变化，重新生成 embedding
- 异步更新 ES 和向量库
- 更新 `updated_at`

### 7.5 删除记忆流程

- 软删除：标记 `is_deleted = true`
- 异步从 ES 和向量库删除
- 释放配额

支持硬删除配置，按需开启。

---

## 8. 部署架构

### 8.1 单机部署（开发/测试）

```
┌─────────────────┐
│   DARE-LTM      │
│   (FastAPI)     │
└────────┬────────┘
         ├─────────────┐
         ↓             ↓
    GaussDB     Elasticsearch
      ↓
  (可选) Pgvector 向量存储
```

适合开发测试，单实例即可运行。

### 8.2 生产集群部署

```
                 ┌─────────────┐
                 │   Nginx     │
                 │  API Gateway│
                 └──────┬──────┘
                        │
         ┌───────────┼───────────┐
         ↓           ↓           ↓
    DARE-LTM     DARE-LTM     DARE-LTM   (多实例，无状态)
         │           │           │
         └───────────┴───────────┘
                     │
         ┌───────────┴───────────┐
         ↓                       ↓
    ┌───────────┐          ┌───────────┐
    │ GaussDB   │          │ Elasticsearch
    │  Cluster  │          │   Cluster  │
    └───────────┘          └───────────┘
```

### 8.3 容器化部署

提供 Dockerfile，docker-compose 一键拉起：

```yaml
# docker-compose.yml
services:
  app:
    build: .
    ports: ["8000:8000"]
    environment:
      - DATABASE_URL=postgresql://...
      - ES_URL=http://elasticsearch:9200
      - EMBEDDING_PROVIDER=openai
    depends_on:
      - db
      - elasticsearch

  db:
    image: enmotech/opengauss:latest
    volumes: [gauss_data:/var/lib/opengauss]

  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.x
    volumes: [es_data:/usr/share/elasticsearch/data]
    environment:
      - discovery.type=single-node

volumes:
  gauss_data:
  es_data:
```

### 8.4 Kubernetes 部署

提供 Helm Chart，支持：

- 自动扩缩容
- 配置管理
- 监控集成
- 健康检查

---

## 9. 数据生命周期管理

### 9.1 TTL 机制

支持每条记忆设置过期时间，到期自动清理：

```sql
ALTER TABLE memories ADD COLUMN expires_at TIMESTAMP WITH TIME ZONE;
```

定时任务每天凌晨清理过期数据。

### 9.2 冷热数据分离

- **热数据**（访问频率高，最近 3 个月）：存储在快速存储，全索引
- **冷数据**（超过 6 个月不访问）：可以压缩归档，查询频率低，保留备份即可
- 自动迁移策略可配置

### 9.3 版本管理

支持同一个记忆的多版本，保留修改历史：

```sql
CREATE TABLE memories_versions (
  id BIGSERIAL PRIMARY KEY,
  memory_id UUID NOT NULL,
  content TEXT NOT NULL,
  changed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
  changed_by UUID,
  version INTEGER
);
```

默认可以不开启，节省存储空间。

### 9.4 备份恢复

- 全量备份：每天凌晨对 GaussDB 做全量备份
- 增量备份：WAL 日志持续备份
- ES 快照备份：定期创建快照
- 支持按时间点恢复

---

## 10. 安全与权限设计

### 10.1 认证

- API Key 认证：每个租户生成一个/多个 API Key
- JWT 认证：支持对接外部认证系统
- IP 白名单：可配置允许访问的 IP 段

### 10.2 权限模型

| 角色 | 权限 |
|------|------|
| 租户管理员 | 所有操作，配额管理，清理数据 |
| 普通用户 | 只能读写自己的记忆 |
| 只读用户 | 只允许检索查询，不能修改删除 |

权限控制到租户级，跨租户数据完全隔离。

### 10.3 数据隔离

- 每个租户的数据在数据库层面通过 `tenant_id` 完全隔离
- Elasticsearch 推荐按租户分索引，物理隔离
- 永远不会出现跨租户数据泄露

### 10.4 限流熔断

- 按租户配置 QPS 限制
- 超过限制返回 429 Too Many Requests
- 保护系统不被突发流量打垮

---

## 11. 性能优化策略

### 11.1 缓存策略

- **热点记忆缓存**：经常访问的记忆内容缓存在 Redis
- **向量缓存**：热门查询的 embedding 结果可以缓存
- **缓存更新**：更新记忆时自动失效对应的缓存

### 11.2 查询优化

- 向量检索只返回 top-k (默认 50)，减少后续计算量
- ES 返回 id 列表，不需要返回全部内容
- 分页查询使用游标滚动，不深翻

### 11.3 写入优化

- 批量写入时，合并 ES 批量操作
- embedding 批量请求，减少网络往返
- 异步同步，不阻塞主写入流程

### 11.4 数据库优化

- 按租户分区，提高查询性能
- 定期 VACUUM 清理死元组
- 索引设计合理，避免过度索引

---

## 12. 监控与运维

### 12.1 监控指标

需要监控以下指标：

| 指标 | 类型 | 说明 |
|------|------|------|
| `ltm.requests.total` | Counter | 总请求数 |
| `ltm.requests.latency` | Histogram | 请求延迟分布 |
| `ltm.memories.total` | Gauge | 总记忆条数 |
| `ltm.memories.bytes_used` | Gauge | 已用存储空间 |
| `ltm.embedding.calls` | Counter | embedding 调用次数 |
| `ltm.sync.errors` | Counter | 同步错误次数 |

### 12.2 健康检查端点

**GET /health**

返回：

```json
{
  "status": "ok",
  "database": "ok",
  "elasticsearch": "ok",
  "vector_db": "ok"
}
```

任一存储不健康返回 503 状态码。

### 12.3 日志

- 结构化 JSON 日志
- 记录每个请求的 tenant_id、latency、status
- 错误日志包含详细上下文

### 12.4 告警规则

- 服务不可用时告警
- 同步错误连续超过 N 次告警
- 存储空间超过 80% 配额告警
- P95 延迟超过阈值告警

---

## 附录

### A. 部署依赖

| 依赖 | 最低版本 | 可选/必需 |
|------|---------|----------|
| Python | 3.10+ | 必需 |
| GaussDB / PostgreSQL | 12+ | 必需 |
| Elasticsearch | 7.10+ | 可选（百万级以上推荐） |
| pgvector | 最新 | 可选（向量存在 GaussDB 时需要） |
| Chroma | 最新 | 可选（独立向量库方案） |

### B. 可选架构方案

**方案一：轻量方案（数据量 < 10万）**

- GaussDB + pgvector
- PostgreSQL 全文检索
- 不需要 ES
- 架构最简单，运维成本最低

**方案二：标准方案（数据量 10万 - 100万）**

- GaussDB (元数据) + Elasticsearch (全文检索) + pgvector/Chroma (向量)
- 功能完整，性能较好

**方案三：大规模方案（数据量 > 100万）**

- GaussDB (元数据) + Elasticsearch (全文检索) + 专业向量库 (Milvus/Wegoav)
- 支撑更大规模数据

---

## 总结

这份设计文档完整定义了：

1. **API 接口**：RESTful 规范，清晰的请求响应格式
2. **Gauss 表结构**：完整的建表语句，索引设计，支持 pgvector 向量存储
3. **Elasticsearch 集成**：Mapping 设计，同步策略，查询方式
4. **内部核心逻辑**：创建/更新/检索详细流程
5. **部署架构**：支持从开发到生产的多种部署方式
6. **运维监控**：完整的监控告警方案

可以基于这个设计直接进行编码实现。
