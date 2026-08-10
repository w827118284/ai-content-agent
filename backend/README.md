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

## 测试

```powershell
.venv\Scripts\python -m pytest
```

## 当前限制

图片生成仍为 Mock。Checkpointer 使用 InMemorySaver，仅支持单进程、单 worker，服务重启后 workflow 状态会丢失。
