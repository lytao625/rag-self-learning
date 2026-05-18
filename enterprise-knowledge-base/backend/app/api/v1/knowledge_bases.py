import shutil
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import get_current_user, require_kb_admin, require_kb_write
from app.db.session import get_db
from app.models import ChunkRecord, Document, IngestionJob, JobStatus, KnowledgeBase, User
from app.schemas.common import DocumentOut, JobOut, KnowledgeBaseCreate, KnowledgeBaseOut
from app.services import parser
from app.services.ingestion import run_ingestion
from app.services import vector_store as vs
from app.utils.audit import write_audit
from app.utils.errors import api_error, get_trace_id

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


@router.get("", response_model=list[KnowledgeBaseOut])
async def list_kbs(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    r = await db.execute(select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc()))
    return list(r.scalars().all())


@router.post("", response_model=KnowledgeBaseOut)
async def create_kb(
    request: Request,
    body: KnowledgeBaseCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_kb_admin)],
):
    tid = get_trace_id(request)
    kb = KnowledgeBase(
        name=body.name,
        description=body.description,
        embedding_model_id=body.embedding_model_id,
        chunk_size=body.chunk_size,
        chunk_overlap=body.chunk_overlap,
        created_by=user.id,
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    Path(get_settings().upload_dir, kb.id).mkdir(parents=True, exist_ok=True)
    await write_audit(
        db,
        user_id=user.id,
        action="kb_create",
        resource_type="knowledge_base",
        resource_id=kb.id,
        detail={"name": kb.name},
        ip=request.client.host if request.client else None,
    )
    return kb


@router.delete("/{kb_id}")
async def delete_kb(
    request: Request,
    kb_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_kb_admin)],
):
    tid = get_trace_id(request)
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise api_error("KB_NOT_FOUND", "知识库不存在", status_code=404, trace_id=tid)
    # delete files
    base = Path(get_settings().upload_dir) / kb_id
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    vs.delete_collection(kb_id)
    await db.delete(kb)
    await db.commit()
    await write_audit(
        db,
        user_id=user.id,
        action="kb_delete",
        resource_type="knowledge_base",
        resource_id=kb_id,
        ip=request.client.host if request.client else None,
    )
    return {"ok": True}


@router.get("/{kb_id}/documents", response_model=list[DocumentOut])
async def list_docs(
    kb_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    r = await db.execute(select(Document).where(Document.knowledge_base_id == kb_id))
    return list(r.scalars().all())


@router.post("/{kb_id}/documents", response_model=JobOut)
async def upload_doc(
    request: Request,
    kb_id: str,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_kb_write)],
):
    tid = get_trace_id(request)
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise api_error("KB_NOT_FOUND", "知识库不存在", status_code=404, trace_id=tid)

    form = await request.form()
    file = form.get("file")
    if file is None or not hasattr(file, "read"):
        raise api_error("NO_FILE", "请使用 multipart 字段名 file 上传文件", trace_id=tid)
    filename = Path(getattr(file, "filename", "upload")).name
    suffix = Path(filename).suffix.lower()
    if suffix not in (".pdf", ".docx", ".txt", ".md", ".xlsx", ".xlsm"):
        raise api_error("UNSUPPORTED_TYPE", "不支持的文件类型", trace_id=tid)

    data = await file.read()
    max_b = get_settings().max_upload_mb * 1024 * 1024
    if len(data) > max_b:
        raise api_error("FILE_TOO_LARGE", f"文件超过 {get_settings().max_upload_mb}MB 限制", trace_id=tid)

    uid = str(uuid.uuid4())
    safe_name = f"{uid}{suffix}"
    dest_dir = Path(get_settings().upload_dir) / kb_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / safe_name
    dest_path.write_bytes(data)

    h = parser.file_sha256(dest_path)
    existing = await db.execute(
        select(Document).where(
            Document.knowledge_base_id == kb_id,
            Document.content_hash == h,
        )
    )
    if existing.scalar_one_or_none():
        dest_path.unlink(missing_ok=True)
        raise api_error("DUPLICATE_DOCUMENT", "相同内容文档已存在", status_code=409, trace_id=tid)

    doc = Document(
        knowledge_base_id=kb_id,
        filename=filename,
        storage_path=str(dest_path),
        content_hash=h,
        uploaded_by=user.id,
    )
    db.add(doc)
    await db.flush()
    job = IngestionJob(document_id=doc.id, status=JobStatus.pending.value, progress=0)
    db.add(job)
    await db.commit()
    await db.refresh(job)

    background_tasks.add_task(run_ingestion, job.id, doc.id)

    await write_audit(
        db,
        user_id=user.id,
        action="document_upload",
        resource_type="document",
        resource_id=doc.id,
        detail={"kb_id": kb_id, "filename": filename},
        ip=request.client.host if request.client else None,
    )
    return job


@router.delete("/{kb_id}/documents/{doc_id}")
async def delete_document(
    request: Request,
    kb_id: str,
    doc_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_kb_write)],
):
    tid = get_trace_id(request)
    doc = await db.get(Document, doc_id)
    if not doc or doc.knowledge_base_id != kb_id:
        raise api_error("DOC_NOT_FOUND", "文档不存在", status_code=404, trace_id=tid)
    r = await db.execute(select(ChunkRecord).where(ChunkRecord.document_id == doc_id))
    ids = [c.id for c in r.scalars().all()]
    if ids:
        vs.delete_ids(kb_id, ids)
    await db.execute(delete(ChunkRecord).where(ChunkRecord.document_id == doc_id))
    await db.execute(delete(IngestionJob).where(IngestionJob.document_id == doc_id))
    p = Path(doc.storage_path)
    if p.exists():
        p.unlink(missing_ok=True)
    await db.delete(doc)
    await db.commit()
    await write_audit(
        db,
        user_id=user.id,
        action="document_delete",
        resource_type="document",
        resource_id=doc_id,
        detail={"kb_id": kb_id},
        ip=request.client.host if request.client else None,
    )
    return {"ok": True}
