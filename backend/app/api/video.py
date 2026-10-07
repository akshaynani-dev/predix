"""Video upload and management endpoints for PREDIX — Phase 2."""

import re
import uuid
import logging
import sqlite3
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.core.config import settings
from app.database.instance import repository
from app.spatial.config import zone_config_path
from app.video_processing.metadata import VideoMetadataError, extract_video_metadata

router = APIRouter()
logger = logging.getLogger(__name__)

# Streaming chunk size: 1 MB — keeps memory low for large uploads
_CHUNK_SIZE = 1024 * 1024


def _safe_filename(name: str) -> str:
    """Strip directory components and replace unsafe characters."""
    name = Path(name).name  # strip any leading directory parts
    name = re.sub(r"[^\w.\-]", "_", name)
    return name or "upload"


def _validate_extension(filename: str) -> None:
    """Raise HTTP 400 if the file extension is not in the allowed list."""
    ext = Path(filename).suffix.lower()
    if ext not in settings.allowed_extensions:
        allowed = ", ".join(e.upper().lstrip(".") for e in settings.allowed_extensions)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported video format. Please upload {allowed}.",
        )


def _validate_mime(content_type: str | None) -> str:
    """Return the normalised MIME type or raise HTTP 400."""
    if not content_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not determine file type. Please upload a valid video file.",
        )
    ct = content_type.lower().split(";")[0].strip()
    if ct not in settings.allowed_mime_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported video format. Please upload MP4, WebM, or MOV.",
        )
    return ct


@router.post("/video/upload", tags=["Video"], status_code=status.HTTP_200_OK)
async def upload_video(file: UploadFile = File(...)) -> dict:
    """
    Accept a video file upload via multipart/form-data.

    Size enforcement is done by streaming in 1 MB chunks and counting bytes.
    This requires no Starlette middleware and works with any FastAPI version.
    """
    # 1. Extension check
    _validate_extension(file.filename or "")

    # 2. MIME check
    content_type = _validate_mime(file.content_type)

    # 3. Prepare destination path
    video_id = str(uuid.uuid4())
    safe_name = _safe_filename(file.filename or "upload.mp4")
    stored_filename = f"{video_id}_{safe_name}"
    dest_path = settings.upload_dir / stored_filename

    # 4. Stream to disk, enforcing size limit mid-stream
    total_bytes = 0
    try:
        with open(dest_path, "wb") as out:
            while True:
                chunk = await file.read(_CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > settings.MAX_UPLOAD_SIZE_BYTES:
                    out.close()
                    dest_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=getattr(status, "HTTP_413_CONTENT_TOO_LARGE", 413),
                        detail="Video exceeds the maximum allowed upload size.",
                    )
                out.write(chunk)
        if total_bytes == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The uploaded video is empty.",
            )
        metadata = extract_video_metadata(dest_path)
    except HTTPException:
        dest_path.unlink(missing_ok=True)
        raise
    except VideoMetadataError as exc:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except OSError as exc:
        dest_path.unlink(missing_ok=True)
        logger.exception("Failed to write uploaded file: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store the uploaded file. Please try again.",
        ) from exc

    finally:
        await file.close()

    try:
        repository.create_session(
            video_id=video_id,
            filename=file.filename or safe_name,
            stored_filename=stored_filename,
            content_type=content_type,
            size_bytes=total_bytes,
            metadata=metadata,
        )
    except (sqlite3.Error, OSError):
        dest_path.unlink(missing_ok=True)
        logger.exception("Could not create session metadata for video %s", video_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not record the uploaded video session.",
        )

    return {
        "status": "uploaded",
        "video_id": video_id,
        "filename": file.filename,
        "stored_filename": stored_filename,
        "content_type": content_type,
        "size_bytes": total_bytes,
        "metadata": metadata,
    }


@router.delete("/video/{video_id}", tags=["Video"], status_code=status.HTTP_200_OK)
async def delete_video(video_id: str) -> dict:
    """
    Delete a previously uploaded video by its video_id.
    Only files whose names begin with {video_id}_ are removed — no arbitrary
    filesystem paths can be targeted. video_id is validated as UUID4.
    """
    try:
        uuid.UUID(video_id, version=4)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid video ID format.",
        )

    prefix = f"{video_id}_"
    upload_dir = settings.upload_dir

    if not upload_dir.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found.")

    matched = [f for f in upload_dir.iterdir() if f.is_file() and f.name.startswith(prefix)]

    if not matched:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found or already deleted.",
        )

    for f in matched:
        f.unlink(missing_ok=True)

    # Also clean up any associated annotated video in analysis_outputs
    if settings.analysis_dir.is_dir():
        annotated_file = settings.analysis_dir / f"{video_id}_annotated.mp4"
        annotated_file.unlink(missing_ok=True)
        (settings.analysis_dir / f"{video_id}_detections.jsonl").unlink(missing_ok=True)
        (settings.analysis_dir / f"{video_id}_events.jsonl").unlink(missing_ok=True)
        (settings.analysis_dir / f"{video_id}_result.json").unlink(missing_ok=True)
        zone_config_path(video_id).unlink(missing_ok=True)

    # Clean up the associated processing state and historical records.
    from app.api.analysis import _analysis_jobs, _jobs_lock
    with _jobs_lock:
        _analysis_jobs.pop(video_id, None)
    repository.delete_session(video_id)

    return {"status": "deleted", "video_id": video_id}
