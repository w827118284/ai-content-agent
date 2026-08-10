# AI Content Operations Agent

基于 FastAPI 和 LangGraph 的 AI 自媒体内容运营工作流。当前已跑通选题、人工选择、文章生成、人工审核、Reject 重写、Approve、视觉知识点提炼和图片生成，并支持 Mock / OpenAI Compatible 文字 LLM 切换。

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

## LLM 模式

默认 `USE_MOCK_LLM=true`，无需 API Key。使用真实文字 LLM 时，在本地 `.env` 中设置：

```dotenv
USE_MOCK_LLM=false
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=
LLM_TEMPERATURE=0.2
```

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

图片生成仍为 Mock。Memory Checkpointer 仅适用于单进程开发和测试；持久化部署应使用 PostgreSQL 模式。
