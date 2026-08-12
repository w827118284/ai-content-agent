# AI Content Operations Agent

基于 FastAPI 和 LangGraph 的 AI 自媒体内容运营工作流。当前已跑通选题、人工选择、文章生成、人工审核、Reject 重写、Approve、视觉知识点提炼和图片生成，并支持文字 LLM 与图片模型的 Mock / Real 切换。

## 环境

- Python 3.11+

## 安装

```powershell
cd backend
python --version  # 确认版本为 3.11+
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

## 运行

```powershell
.venv\Scripts\python -m uvicorn app.main:app --reload
```

Swagger：http://127.0.0.1:8000/docs  
健康检查：http://127.0.0.1:8000/health

## 用户认证

Phase 6 使用 `pwdlib[argon2]` 保存密码哈希，并使用 PyJWT 签发 HS256 Bearer Access Token。启动前必须在本地 `.env` 配置至少 32 bytes 的随机 Secret（本地可用 `secrets.token_hex(32)` 生成），源码没有默认 Secret：

```dotenv
JWT_SECRET_KEY=
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
```

JWT 只包含 `sub`、`iat`、`exp`。`sub` 是用户 UUID；密码、数据库连接与外部 API Key 不进入 token。

## LLM 模式

默认 `USE_MOCK_LLM=true`，无需 API Key。使用真实文字 LLM 时，在本地 `.env` 中设置：

```dotenv
USE_MOCK_LLM=false
LLM_API_KEY=
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-pro
LLM_MAX_CONCURRENCY=4
LLM_REQUESTS_PER_MINUTE=30
LLM_MAX_ATTEMPTS=2
LLM_RETRY_BASE_DELAY_SECONDS=0.5
```

真实文字模型通过 DeepSeek 的 OpenAI-compatible Chat Completions API 调用，SDK 自动重试保持关闭。只有 timeout、connection、HTTP 429 和 HTTP 5xx 会进行最多一次 application-level retry，因此每个 LLM operation 最多 2 次总 attempt。400、401、403、404 与业务 JSON/响应解析失败不会 retry。项目只从本地环境变量读取 `LLM_API_KEY`，不会读取 Codex CLI 配置或 `~/.codex/auth.json`；工作流状态仍由 LangGraph Checkpointer 管理。

## LangSmith 可观测性

LangSmith tracing 是可选能力，默认关闭；没有 LangSmith Key 时不影响 Backend、REST、SSE、Mock 或真实 Provider 工作流：

```dotenv
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=ai-content-agent
LANGSMITH_ENDPOINT=
LANGSMITH_WORKSPACE_ID=
LANGSMITH_HIDE_INPUTS=true
LANGSMITH_HIDE_OUTPUTS=true
```

启用后，REST 与 SSE 都通过同一个 LangGraph `RunnableConfig` 记录顶层 workflow、Graph node 和 LangChain LLM 调用。顶层 run name 为 `content_workflow.start` 或 `content_workflow.resume`；metadata 仅包含 `thread_id`、`project_id`、`user_id`、`workflow_action`、`transport`、`llm_mode`、`image_mode`，不包含主题、文章、审核意见、JWT 或 API Key。输入输出默认隐藏，如需改变隐私策略必须显式修改对应环境变量。

## 图片模式

默认 `USE_MOCK_IMAGE=true`，单元测试不会调用收费接口。使用 OpenAI-compatible Image API 时，在本地 `.env` 中配置：

```dotenv
USE_MOCK_IMAGE=false
IMAGE_API_KEY=
IMAGE_BASE_URL=https://api.iotwq.top/v1
IMAGE_MODEL=gpt-image-2
IMAGE_SIZE=1008x1344
IMAGE_QUALITY=auto
IMAGE_OUTPUT_FORMAT=png
IMAGE_MODERATION=auto
IMAGE_N=1
IMAGE_MAX_CONCURRENCY=3
IMAGE_REQUESTS_PER_MINUTE=10
IMAGE_OUTPUT_DIR=outputs/images
IMAGE_PUBLIC_PREFIX=/media/images
IMAGE_TIMEOUT_SECONDS=300
```

服务通过 OpenAI-compatible `images/generations` 接口生成图片，同时支持 `b64_json` 和临时 `url` 响应。图片会立即保存到 `IMAGE_OUTPUT_DIR`，State 中只记录 `/media/images/<filename>` 形式的相对公开 URL。真实生图请求的 SDK 与 application-level 自动 retry 均关闭：timeout、connection、429 或 5xx 也只发送 1 次收费 POST，因为客户端无法判断 Provider 是否已经接受请求或扣费。

## Provider 调用治理

真实 LLM 与真实图片 Provider 分别维护独立的进程内并发限制、每分钟请求限制和 circuit breaker；Mock Provider 完全绕过这些治理状态：

```dotenv
PROVIDER_BREAKER_FAILURE_THRESHOLD=3
PROVIDER_BREAKER_COOLDOWN_SECONDS=30
```

breaker 只统计 timeout、connection、HTTP 429 和 HTTP 5xx。连续达到阈值后进入 OPEN，cooldown 到期后只允许一个 HALF_OPEN probe；成功恢复 CLOSED，失败重新 OPEN。401、403、400、404、业务解析和用户输入错误不计入 breaker。

日志仅记录 provider、固定 operation、安全 category、attempt、breaker state 和异常类型，不记录 prompt、主题、文章、feedback、图片 URL、API Key、Authorization 或 raw Provider exception。

当前 rate limiter 和 circuit breaker 都是 process-local：它们不跨 backend replica 共享，breaker 状态也不会在服务重启后持久化。多 replica 部署需要在 Redis、API gateway 或 Provider gateway 层实现分布式全局限流与协调保护。

## Checkpointer 模式

默认使用 Memory Checkpointer，适合本地开发和测试，服务重启后状态会丢失：

```dotenv
CHECKPOINTER_BACKEND=memory
LANGGRAPH_STRICT_MSGPACK=true
```

需要持久化工作流时切换到 PostgreSQL：

```dotenv
CHECKPOINTER_BACKEND=postgres
DATABASE_URL=postgresql://postgres:password@localhost:5432/ai_content_agent
LANGGRAPH_STRICT_MSGPACK=true
```

PostgreSQL 模式会在应用启动时运行 LangGraph Checkpointer 的 `setup()` 和 migrations，并在应用生命周期内复用同一个 saver 和 compiled graph。服务重启后，可使用原 `thread_id` 继续读取和恢复工作流。

LangGraph 自动维护的 checkpoint 表只保存工作流执行状态，不是项目的业务历史表或任务列表。

## 历史任务

PostgreSQL 模式下，应用同时维护两类彼此隔离的数据：

- LangGraph Checkpointer 管理 `checkpoints`、`checkpoint_blobs`、`checkpoint_writes` 和 `checkpoint_migrations`，它们是工作流状态的唯一真源。
- SQLAlchemy 管理 `content_projects`，只保存历史列表所需的摘要、状态和 `thread_id`，不复制文章、视觉知识点或图片地址。

`GET /api/v1/projects` 支持 `limit`、`offset`，并在 SQL 查询中按当前认证用户过滤。读取或恢复 workflow 时，API 会先校验 `content_projects` ownership，再访问 LangGraph checkpoint；其他用户的 `thread_id` 与不存在的 `thread_id` 均返回 404。

Phase 5 遗留的 `user_id IS NULL` 项目保持 unowned，不会显示给普通用户，也不会自动分配给首个注册用户。生产数据如需归属迁移，应另行执行显式、可审计的数据迁移。

## Business Schema Migration

Alembic 只管理 `users`、`content_projects` 与 `alembic_version`。LangGraph 的 `checkpoints`、`checkpoint_blobs`、`checkpoint_writes`、`checkpoint_migrations` 仍完全由 `AsyncPostgresSaver.setup()` 管理，并在 Alembic autogenerate 中被排除。

全新空数据库直接执行：

```powershell
.venv\Scripts\python -m alembic upgrade head
```

从已经存在 `content_projects`、但没有 `alembic_version` 的 Phase 5 数据库首次升级时，先核对表字段、约束与索引确实匹配 `0001_phase5_baseline`，再执行：

```powershell
.venv\Scripts\python -m alembic stamp 0001_phase5_baseline
.venv\Scripts\python -m alembic upgrade head
```

后续部署只需执行 `alembic upgrade head`。可用以下命令检查版本与模型差异：

```powershell
.venv\Scripts\python -m alembic current
.venv\Scripts\python -m alembic history
.venv\Scripts\python -m alembic check
```

FastAPI startup 不执行 `metadata.create_all()`，只创建 AsyncEngine/sessionmaker 并通过 `SELECT 1` 检查业务数据库可用性。隔离测试数据库仍可使用 `initialize_business_database()` 快速建表。

Windows 下使用 Psycopg async 连接 PostgreSQL 时，显式使用 SelectorEventLoop 启动 Uvicorn：

```powershell
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --loop asyncio:SelectorEventLoop
```

## 测试

```powershell
.venv\Scripts\python -m pytest
```

当前 Windows 开发机若在 pytest 创建缓存目录时退出卡顿，可临时禁用 cacheprovider：

```powershell
.venv\Scripts\python -m pytest -p no:cacheprovider
```

该参数仅用于绕过本机 pytest 缓存文件系统问题，不是 LangGraph 或 PostgreSQL 的业务要求。

## 当前限制

真实图片 URL 尚未转存永久对象存储。Memory Checkpointer 仅适用于单进程开发和测试；用户、ownership、持久化工作流与历史列表需要 PostgreSQL 模式。本阶段只提供短期 Access Token，不包含 Refresh Token、RBAC 或 OAuth。
