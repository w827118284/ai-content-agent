# AI Content Operations Agent

## 1. 项目简介

AI Content Operations Agent 是一个面向 AI 编程教育内容团队的可恢复内容生产工作流。
用户输入内容方向后，系统生成 5 个候选选题，由用户人工选择；随后 AI 生成技术文章，
用户可以反复 Reject 并给出修改意见，直到 Approve。最终系统从定稿文章提炼 3 到 5 个
视觉知识点，并生成适合小红书发布的竖版知识卡片。

长文章面向微信公众号，视觉卡片面向小红书。项目重点不是一次性调用模型，而是演示
LangGraph 状态编排、Human-in-the-loop、持久化恢复、多用户 ownership、SSE 实时进度、
真实 Provider 解耦以及失败治理如何组合成一个可运行的 AI 应用。

## 2. Demo Workflow

```text
Topic Direction
      |
      v
Generate 5 Topics
      |
      v
Human Select (interrupt)
      |
      v
Generate Article
      |
      v
Human Review (interrupt)
   |             |
 Reject        Approve
   |             |
   v             v
Rewrite       Extract Visuals
   |             |
   +-------> Review
                 |
                 v
          Generate Images
                 |
                 v
             Completed
```

工作流在选题和文章审核处由 LangGraph `interrupt()` 暂停，并通过同一 `thread_id` 下的
`Command(resume=...)` 恢复。Reject 会回到文章生成节点，Approve 才会进入视觉提炼和生图。

## 3. Architecture

```text
Browser / React
      |
      v
Nginx :8080
      |
      v
FastAPI REST + SSE
      |
      v
LangGraph Workflow
   |                 |
   v                 v
PostgreSQL       Provider Services
   |             |             |
   |             v             v
   |          DeepSeek     gpt-image-2
   |
   +-- LangGraph checkpoints
   +-- users / content_projects
```

FastAPI 只处理认证、ownership、HTTP/SSE 协议和历史摘要同步。工作流节点、条件边和
interrupt/resume 语义由 LangGraph 负责。LLM 与图片生成位于独立 service，Mock 和 Real
模式通过环境变量切换。

更完整的组件边界、状态转换和失败语义见 [Architecture](docs/ARCHITECTURE.md)。部署说明见
[Deployment](DEPLOYMENT.md)。

## 4. Tech Stack

Backend:

- Python 3.11+，当前验证环境为 Python 3.12
- FastAPI、Pydantic、Uvicorn
- LangGraph 1.x、LangChain、LangSmith 可选 tracing
- SQLAlchemy Async、Alembic、Psycopg
- PostgreSQL 18、LangGraph `AsyncPostgresSaver`

Frontend:

- React 19、TypeScript、Vite
- Fetch streaming SSE
- Vitest、Testing Library

Infrastructure:

- Docker Compose
- Nginx
- PostgreSQL named volume
- Generated image named volume

AI Providers:

- Text: DeepSeek `deepseek-v4-pro`，OpenAI-compatible Chat Completions
- Image: configurable OpenAI-compatible Image API，当前模型 `gpt-image-2`
- Image output: `1008x1344`，竖版 3:4

## 5. Key Engineering Decisions

### Human-in-the-loop

人工决策不是 Controller 中的临时分支，而是 Graph 的正式节点。`interrupt()` 把等待状态
写入 checkpoint；用户关闭网页或服务重启后，仍可用原 `thread_id` 恢复。Human node 在
interrupt 前不执行收费调用或业务数据库写入，避免节点恢复时重复副作用。

### Checkpoint separation

LangGraph checkpoint 是完整 workflow state 的唯一真源。业务表只保存用户、`thread_id`、
方向、选中标题、状态和修改次数，用于 ownership 与历史列表。Alembic 只管理业务表；
checkpoint 表由 `AsyncPostgresSaver.setup()` 管理。

### REST and SSE

REST 用于状态读取及兼容调用，SSE 用于 start/resume 的节点级进度。该流程是服务器单向
推送，不需要 WebSocket 的双向长连接。SSE 只发送 `meta`、`progress`、`interrupt`、
`completed` 和脱敏 `error`，不做 token streaming。

### LLM retry vs image no retry

LLM 只对 timeout、connection、HTTP 429 和 HTTP 5xx 做最多一次 application retry，
总 attempt 不超过 2，SDK retry 固定为 0。图片生成 POST 是收费且非幂等操作，Provider
可能已经接受请求或扣费，因此 application 和 SDK 自动 retry 都为 0。

### Provider governance

真实 LLM 和图片 Provider 分别拥有并发限制、滑动窗口 rate limiter 和 circuit breaker。
breaker 支持 CLOSED、OPEN、HALF_OPEN，并确保 HALF_OPEN 只放行一个 probe operation。
Mock service 不经过真实 Provider 的治理状态。

### Security boundary

JWT 的 `sub` 绑定用户 UUID。所有 state、resume、SSE resume 与 history 访问先通过业务表
校验 `user_id + thread_id`，再读取 checkpoint。Provider 日志只记录安全 category、操作名、
attempt、breaker state 和异常类型，不记录 prompt、文章、token、URL 或 raw exception。
LangSmith 默认关闭，并默认隐藏输入输出。

Provider 返回临时图片 URL 时，后端只允许 http/https、公网 IP，并对每一跳重定向重新
校验后再下载。生成结果保存到本地目录或 Docker volume，Graph State 只存相对公开 URL。

## 6. Local Development

完整交互式应用需要 PostgreSQL，因为登录、ownership、历史记录和持久化 checkpoint 都
依赖数据库。`.env.example` 中的 `memory` 是安全的开发默认，适合单元测试和工作流学习；
完整登录、history 和 restart recovery 验收使用 `postgres`。

### Backend

```powershell
cd E:\ai_content_agent\backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

复制后，在 ignored 的 `backend/.env` 中至少设置：

```env
CHECKPOINTER_BACKEND=postgres
DATABASE_URL=<local PostgreSQL URL>
JWT_SECRET_KEY=<at least 32-byte random secret>
```

开发和回归默认保持 `USE_MOCK_LLM=true`、`USE_MOCK_IMAGE=true`。

```powershell
.venv\Scripts\python -m alembic upgrade head
.venv\Scripts\python -m uvicorn app.main:app --reload
```

Backend: `http://127.0.0.1:8000`<br>
Swagger: `http://127.0.0.1:8000/docs`<br>
Health: `http://127.0.0.1:8000/health`

### Frontend

```powershell
cd E:\ai_content_agent\frontend
npm ci
Copy-Item .env.example .env
npm run dev
```

Frontend: `http://localhost:5173`

## 7. Docker Compose

```powershell
cd E:\ai_content_agent
Copy-Item .env.docker.example .env.docker
```

在 ignored 的 `.env.docker` 中替换数据库密码、`DATABASE_URL` 和 JWT secret。Mock smoke
不需要任何真实 Provider key。

```bash
docker compose --env-file .env.docker up --build -d
docker compose --env-file .env.docker ps -a
```

访问 `http://localhost:8080`。只有 Nginx 的 8080 端口映射到宿主机；Backend 与 PostgreSQL
只在 Compose network 中暴露。`migrate` 成功退出后 Backend 才会启动。

## 8. Environment Variables

App:

- `CONTENT_AGENT_APP_NAME`: FastAPI 应用名
- `CONTENT_AGENT_APP_VERSION`: 应用版本
- `CONTENT_AGENT_API_V1_PREFIX`: API v1 前缀
- `CORS_ORIGINS`: 允许的前端 origin 列表

Database:

- `CHECKPOINTER_BACKEND`: `memory` 或 `postgres`
- `DATABASE_URL`: 业务数据库与 checkpoint PostgreSQL 连接
- `LANGGRAPH_STRICT_MSGPACK`: checkpoint 安全序列化限制

Auth:

- `JWT_SECRET_KEY`: HS256 签名 secret，至少 32 UTF-8 bytes
- `JWT_ALGORITHM`: 当前仅允许 HS256
- `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`: access token 有效期

LLM:

- `USE_MOCK_LLM`: Mock/Real 开关
- `LLM_API_KEY`: Real LLM key
- `LLM_BASE_URL`: DeepSeek-compatible API base URL
- `LLM_MODEL`: 文字模型名
- `LLM_MAX_CONCURRENCY`: 进程内最大并发
- `LLM_REQUESTS_PER_MINUTE`: 进程内每分钟请求上限
- `LLM_MAX_ATTEMPTS`: 总 attempt，取值 1 或 2
- `LLM_RETRY_BASE_DELAY_SECONDS`: application retry 等待时间

Image:

- `USE_MOCK_IMAGE`: Mock/Real 开关
- `IMAGE_API_KEY`: Real image key
- `IMAGE_BASE_URL`: OpenAI-compatible Image API base URL
- `IMAGE_MODEL`: 图片模型名
- `IMAGE_SIZE`: 图片输出尺寸
- `IMAGE_QUALITY`: 图片质量参数
- `IMAGE_OUTPUT_FORMAT`: png、jpeg 或 webp
- `IMAGE_MODERATION`: Provider moderation 参数
- `IMAGE_N`: 单次请求图片数，固定为 1
- `IMAGE_MAX_CONCURRENCY`: 图片最大并发
- `IMAGE_REQUESTS_PER_MINUTE`: 进程内每分钟请求上限
- `IMAGE_OUTPUT_DIR`: 本地持久化目录
- `IMAGE_PUBLIC_PREFIX`: 静态 URL 前缀
- `IMAGE_TIMEOUT_SECONDS`: 图片请求超时

LangSmith:

- `LANGSMITH_TRACING`: tracing 开关
- `LANGSMITH_API_KEY`: LangSmith key
- `LANGSMITH_PROJECT`: project 名
- `LANGSMITH_ENDPOINT`: 可选 endpoint
- `LANGSMITH_WORKSPACE_ID`: 可选 workspace
- `LANGSMITH_HIDE_INPUTS`: 隐藏 trace inputs
- `LANGSMITH_HIDE_OUTPUTS`: 隐藏 trace outputs

Provider governance:

- `PROVIDER_BREAKER_FAILURE_THRESHOLD`: 连续失败阈值
- `PROVIDER_BREAKER_COOLDOWN_SECONDS`: OPEN cooldown

## 9. Testing

Backend:

```powershell
cd backend
.venv\Scripts\python -m pytest -p no:cacheprovider
```

Frontend:

```powershell
cd frontend
npm test
npm run build
```

Docker smoke 应使用 Mock LLM、Mock Image，并覆盖注册、登录、start、select、reject、approve、
completed、5 张 Mock 图片、history 和重启恢复。测试不应调用收费 Provider。

## 10. Current Limitations

- Rate limiter 与 circuit breaker 是 process-local，不跨 backend replica 共享，重启后状态清空。
- 当前部署是 single-region、single-backend demo，没有 Redis 或 gateway 级分布式协调。
- 同一 thread 的并发 resume 没有跨进程 idempotency key，UI 通过 busy 状态降低重复操作风险。
- SSE 客户端断开会传播 cancellation，不会在后台偷偷重试收费调用；中途中止的任务可能需要新建。
- Generated images 保存在本地目录或 Docker volume，没有对象存储、CDN、备份和生命周期策略。
- `/media/images/<uuid>` 不要求 JWT。文件名使用不可预测的 UUID，但任何获得 URL 的人都可访问，
  因此它不是严格的跨用户私有媒体方案。
- 临时图片 URL 会阻止本地、私网、link-local 和重定向到私网；生产环境仍应使用网络层 egress
  policy 防御 DNS rebinding 等应用层校验无法完全消除的风险。
- Access Token 当前保存在 localStorage，没有 Refresh Token、RBAC、OAuth 或 HttpOnly Cookie。
- LangSmith 是可选能力，默认关闭且隐藏输入输出。
- Docker secrets 当前通过 ignored env file 注入，未接入外部 secret manager。
