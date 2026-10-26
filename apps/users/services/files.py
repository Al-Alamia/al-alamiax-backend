import os
import re
import zipfile

from django.db import transaction

from apps.users.admin_permissions import can_manage_files
from apps.users.models import UserFile
from apps.users.types import FileCategory

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TITLE = 150
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# detected type -> (stored extension, content type, accepted client extensions)
_TYPES = {
    "pdf": (".pdf", "application/pdf", {".pdf"}),
    "jpeg": (".jpg", "image/jpeg", {".jpg", ".jpeg"}),
    "png": (".png", "image/png", {".png"}),
    "webp": (".webp", "image/webp", {".webp"}),
    "docx": (".docx", DOCX_TYPE, {".docx"}),
}
_EXT_BY_CONTENT_TYPE = {v[1]: v[0] for v in _TYPES.values()}


class FileError(Exception):
    def __init__(self, type, message, status=400):
        super().__init__(message)
        self.type = type
        self.message = message
        self.status = status


def _detect(upload):
    """Detected type key from the magic bytes (never from the client name), or None."""
    head = upload.read(12)
    upload.seek(0)
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(upload) as archive:
                return "docx" if "word/document.xml" in archive.namelist() else None
        except zipfile.BadZipFile:
            return None
        finally:
            upload.seek(0)
    return None


def safe_download_name(title: str, content_type: str) -> str:
    base = re.sub(r"[^\w\- ]", "_", title or "").strip(" .") or "file"
    return base + _EXT_BY_CONTENT_TYPE.get(content_type, "")


def save_user_file(actor, user, title, category, upload) -> UserFile:
    if not can_manage_files(actor, user):
        raise FileError("forbidden", "You are not allowed to manage these files", 403)
    if not isinstance(title, str) or not title.strip():
        raise FileError("invalid", "'title' is required.")
    title = title.strip()
    if len(title) > MAX_TITLE:
        raise FileError("invalid", f"'title' is too long (max {MAX_TITLE}).")
    if category not in FileCategory.values:
        raise FileError("invalid", "'category' must be one of: " + ", ".join(FileCategory.values) + ".")
    if upload is None:
        raise FileError("invalid", "'file' is required.")
    if upload.size > MAX_FILE_BYTES:
        raise FileError("file_too_large", "The file must be 10 MB or smaller.")
    kind = _detect(upload)
    client_ext = os.path.splitext(upload.name or "")[1].lower()
    if kind is None or client_ext not in _TYPES[kind][2]:
        raise FileError("file_type", "Allowed files: PDF, JPG, PNG, WEBP or DOCX.")
    ext, content_type, _ = _TYPES[kind]
    upload.name = f"file{ext}"  # never trust the client's extension
    return UserFile.objects.create(
        user=user, title=title, category=category, file=upload, size=upload.size,
        content_type=content_type, uploaded_by=actor)


def delete_user_file(actor, f: UserFile) -> None:
    if not can_manage_files(actor, f.user):
        raise FileError("forbidden", "You are not allowed to manage these files", 403)
    name, storage = f.file.name, f.file.storage
    with transaction.atomic():
        f.delete()
    if name:
        storage.delete(name)
