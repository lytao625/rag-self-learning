from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    code: str
    message: str
    trace_id: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: str


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., max_length=256)
    description: str = ""
    embedding_model_id: str = ""
    chunk_size: int = 512
    chunk_overlap: int = 80
    use_rerank: bool = True
    rerank_top_k: int = 5
    search_top_k: int = 20


class KnowledgeBaseOut(BaseModel):
    id: str
    name: str
    description: str
    embedding_model_id: str
    chunk_size: int
    chunk_overlap: int
    use_rerank: bool
    rerank_top_k: int
    search_top_k: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# 新增：知识库配置更新模型
class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=256)
    description: Optional[str] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    use_rerank: Optional[bool] = None
    rerank_top_k: Optional[int] = None
    search_top_k: Optional[int] = None


class DocumentOut(BaseModel):
    id: str
    knowledge_base_id: str
    filename: str
    content_hash: str
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class JobOut(BaseModel):
    id: str
    document_id: str
    status: str
    progress: int
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatMessageOut(BaseModel):
    id: str
    role: str
    content: str
    citations_json: Optional[dict[str, Any]] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatRequest(BaseModel):
    knowledge_base_id: str
    session_id: Optional[str] = None
    message: str
    stream: bool = True
    top_k: int = 6


class SearchRequest(BaseModel):
    knowledge_base_id: str
    query: str
    top_k: int = 8


class SessionOut(BaseModel):
    id: str
    knowledge_base_id: str
    title: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditOut(BaseModel):
    id: str
    user_id: Optional[str]
    action: str
    resource_type: str
    resource_id: Optional[str]
    detail: Optional[dict[str, Any]]
    ip: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RuntimeLLMConfigOut(BaseModel):
    llm_model: str
    embedding_model: str
    openai_api_base: str
    has_api_key: bool


class RuntimeLLMConfigUpdate(BaseModel):
    llm_model: Optional[str] = None
    embedding_model: Optional[str] = None
    openai_api_base: Optional[str] = None
