# 企业级智能知识库（RAG）

## 本地开发

### 后端

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
# 配置环境变量：OPENAI_API_KEY（必填）、OPENAI_API_BASE、LLM_MODEL、EMBEDDING_MODEL 等
set DATABASE_URL=sqlite+aiosqlite:///./data/app.db
set CHROMA_PATH=./data/chroma
set UPLOAD_DIR=./data/uploads
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

浏览器访问 `http://localhost:5173`。演示账号见登录框说明（默认 `admin` / `admin123`）。

## Docker Compose

在项目根目录：

```bash
set OPENAI_API_KEY=sk-...
docker compose up --build
```

- API: `http://localhost:8000`
- 前端: `http://localhost:5173`（Vite 将 `/api` 代理到 `api` 容器）

数据库默认使用 Compose 中的 PostgreSQL；本地单文件 SQLite 可设置 `DATABASE_URL=sqlite+aiosqlite:///./data/app.db`。

## API 文档

启动后端后访问 `http://127.0.0.1:8000/docs`（OpenAPI）。
