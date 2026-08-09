# AI Content Operations Agent

基于 FastAPI 和 LangGraph 的 AI 自媒体内容运营工作流。第一阶段使用全 Mock 服务和 InMemorySaver，跑通选题、人工选择、文章生成、人工审核、Reject 重写、Approve、视觉知识点提炼和图片生成。

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

## 测试

```powershell
.venv\Scripts\python -m pytest
```

## 当前限制

LLM 和图片生成均为 Mock。Checkpointer 使用 InMemorySaver，仅支持单进程、单 worker，服务重启后 workflow 状态会丢失。
