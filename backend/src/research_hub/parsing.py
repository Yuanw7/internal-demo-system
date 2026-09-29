from __future__ import annotations

import io
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader

from .models import DocumentInput

SUPPORTED = {".txt", ".md", ".json", ".jsonl", ".eml", ".pdf"}
SUPPORTED_CONTAINERS = {".zip"}
PARSER_VERSION = "local-text-v2"
MAX_ARCHIVE_ENTRIES = 2_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024


@dataclass
class ParsedDocument:
    title: str
    body: str
    published_at: str = ""
    url: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    pages: list[tuple[int, int, int]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"p", "div", "br", "li", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def canonicalize(text: str) -> str:
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


def _iso_date(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def filename_date(name: str) -> str:
    dates: set[datetime] = set()
    for year, month, day in re.findall(r"(?<!\d)(20\d{2})[-_](\d{2})[-_](\d{2})(?!\d)", name):
        try:
            dates.add(datetime(int(year), int(month), int(day), tzinfo=UTC))
        except ValueError:
            pass
    month_names = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    for day, month_name, year in re.findall(
        r"(?<!\d)(\d{1,2})[-_ ]([A-Za-z]{3})[-_ ](20\d{2})(?!\d)", name
    ):
        month = month_names.get(month_name.lower())
        if month is None:
            continue
        try:
            dates.add(datetime(int(year), month, int(day), tzinfo=UTC))
        except ValueError:
            pass
    return next(iter(dates)).isoformat() if len(dates) == 1 else ""


def _document_title(name: str) -> str:
    title = Path(name).name
    while Path(title).suffix.lower() == ".pdf":
        title = Path(title).stem
    return title or Path(name).stem


def parse_bytes(name: str, raw: bytes, *, max_file_mb: int = 20, max_pages: int = 300) -> list[ParsedDocument]:
    if len(raw) > max_file_mb * 1024 * 1024:
        raise ValueError("file_size_limit")
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError("unsupported_format")
    if suffix == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(raw), strict=False)
            if reader.is_encrypted:
                raise ValueError("encrypted_pdf")
            if len(reader.pages) > max_pages:
                raise ValueError("pdf_page_limit")
            sections: list[str] = []
            pages: list[tuple[int, int, int]] = []
            warnings: list[str] = []
            position = 0
            for number, page in enumerate(reader.pages, 1):
                text = canonicalize(page.extract_text() or "")
                if not text:
                    warnings.append(f"page_{number}_ocr_required_or_blank")
                if sections:
                    position += 2
                pages.append((number, position, position + len(text)))
                sections.append(text)
                position += len(text)
            body = "\n\n".join(sections)
            if not body.strip():
                raise ValueError("pdf_has_no_extractable_text_ocr_required")
            return [ParsedDocument(_document_title(name), body, pages=pages, warnings=warnings)]
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("pdf_parse_failed") from exc
    if suffix == ".eml":
        mail = BytesParser(policy=policy.default).parsebytes(raw)
        part = mail.get_body(preferencelist=("plain", "html"))
        if part is None:
            raise ValueError("email_has_no_text_body")
        body = part.get_content()
        if part.get_content_type() == "text/html":
            parser = _HTMLText()
            parser.feed(body)
            body = "".join(parser.parts)
        warnings = ["email_attachment_not_parsed"] if any(mail.iter_attachments()) else []
        try:
            published = _iso_date(str(mail.get("date", "")))
        except (ValueError, TypeError, OverflowError):
            published = ""
            warnings.append("invalid_email_date")
        sender_name, sender_address = parseaddr(str(mail.get("from", "")))
        metadata: dict[str, str] = {}
        if sender_name.strip():
            metadata["email_from_name"] = canonicalize(sender_name)
        if sender_address.strip():
            metadata["email_from_address"] = sender_address.strip().casefold()
        message_id = str(mail.get("message-id", "")).strip()
        if message_id:
            metadata["email_message_id"] = message_id[:500]
        return [
            ParsedDocument(
                str(mail.get("subject", Path(name).stem)),
                canonicalize(body),
                published_at=published,
                metadata=metadata,
                warnings=warnings,
            )
        ]
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("utf8_required") from exc
    if suffix in {".json", ".jsonl"}:
        values = (
            [json.loads(line) for line in text.splitlines() if line.strip()]
            if suffix == ".jsonl"
            else json.loads(text)
        )
        values = values if isinstance(values, list) else [values]
        documents = []
        for value in values:
            item = DocumentInput.model_validate(value)
            documents.append(
                ParsedDocument(
                    item.title,
                    canonicalize(item.body),
                    item.published_at,
                    item.url,
                    item.metadata,
                    item.pages,
                )
            )
        return documents
    return [ParsedDocument(Path(name).stem, canonicalize(text))]


def _append_documents(
    documents: list[DocumentInput],
    *,
    display_name: str,
    external_id: str,
    raw: bytes,
    extra_metadata: dict[str, str] | None = None,
) -> None:
    parsed = parse_bytes(display_name, raw)
    for index, document in enumerate(parsed):
        metadata = dict(document.metadata)
        metadata.update(extra_metadata or {})
        metadata.update(
            {
                "file_name": Path(display_name).name,
                "parser_version": PARSER_VERSION,
                "parser_warnings": ";".join(document.warnings)[:1000],
            }
        )
        documents.append(
            DocumentInput(
                external_id=f"{external_id}#{index}",
                title=document.title,
                body=document.body,
                published_at=document.published_at or filename_date(Path(display_name).name),
                url=document.url,
                metadata=metadata,
                pages=document.pages,
            )
        )


def _append_zip(
    archive: Path,
    archive_id: str,
    documents: list[DocumentInput],
    errors: list[dict[str, str]],
) -> None:
    try:
        with ZipFile(archive) as bundle:
            entries = [item for item in bundle.infolist() if not item.is_dir()]
            if len(entries) > MAX_ARCHIVE_ENTRIES:
                raise ValueError("archive_entry_limit")
            if sum(item.file_size for item in entries) > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise ValueError("archive_uncompressed_size_limit")
            for item in entries:
                entry = PurePosixPath(item.filename)
                item_id = f"{archive_id}!/{item.filename}@{item.header_offset}"
                if entry.is_absolute() or ".." in entry.parts:
                    errors.append({"file": item_id, "error": "unsafe_archive_path"})
                    continue
                if entry.suffix.lower() not in SUPPORTED:
                    continue
                if item.flag_bits & 0x1:
                    errors.append({"file": item_id, "error": "encrypted_archive_entry"})
                    continue
                if item.file_size > 20 * 1024 * 1024:
                    errors.append({"file": item_id, "error": "file_size_limit"})
                    continue
                try:
                    raw = bundle.read(item)
                    _append_documents(
                        documents,
                        display_name=item.filename,
                        external_id=item_id,
                        raw=raw,
                        extra_metadata={
                            "archive_name": archive.name,
                            "archive_entry": item.filename,
                        },
                    )
                except (OSError, ValueError) as exc:
                    errors.append({"file": item_id, "error": str(exc) or "parse_failed"})
    except (BadZipFile, OSError, ValueError) as exc:
        errors.append({"file": archive_id, "error": str(exc) or "archive_parse_failed"})


def documents_from_path(path: Path) -> tuple[list[DocumentInput], list[dict[str, str]]]:
    path = path.resolve()
    if not path.exists():
        raise ValueError("input_path_not_found")
    root = path if path.is_dir() else path.parent
    paths = sorted(path.rglob("*")) if path.is_dir() else [path]
    documents: list[DocumentInput] = []
    errors: list[dict[str, str]] = []
    for item in paths:
        if not item.is_file() or item.suffix.lower() not in SUPPORTED | SUPPORTED_CONTAINERS:
            continue
        if not item.resolve().is_relative_to(root):
            errors.append({"file": item.name, "error": "outside_import_root"})
            continue
        relative = item.relative_to(root).as_posix()
        if item.suffix.lower() == ".zip":
            _append_zip(item, relative, documents, errors)
            continue
        try:
            _append_documents(
                documents,
                display_name=item.name,
                external_id=relative,
                raw=item.read_bytes(),
            )
        except (OSError, ValueError) as exc:
            errors.append({"file": relative, "error": str(exc) or "parse_failed"})
    return documents, errors
