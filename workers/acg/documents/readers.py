from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from acg.protocol import fail


def read_document_source(path: str) -> str:
    document_path = Path(path)
    if not document_path.exists():
        fail(f"文档不存在：{document_path}")
    suffix = document_path.suffix.lower()
    if suffix in {".txt", ".md", ".markdown"}:
        return read_text_document(document_path)
    if suffix == ".docx":
        return read_docx_document(document_path)
    if suffix == ".epub":
        return read_epub_document(document_path)
    if suffix == ".pdf":
        return read_pdf_document(document_path)
    fail("暂不支持这个文档格式。请使用 TXT、Markdown、DOCX、EPUB 或 PDF。")


def read_text_document(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def read_docx_document(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.startswith("word/") and name.endswith(".xml")]
            ordered = ["word/document.xml"] + [name for name in names if name != "word/document.xml"]
            paragraphs: list[str] = []
            namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            for name in ordered:
                if name not in archive.namelist():
                    continue
                root = ElementTree.fromstring(archive.read(name))
                for paragraph in root.findall(".//w:p", namespace):
                    texts = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
                    line = "".join(texts).strip()
                    if line:
                        paragraphs.append(line)
            text = "\n\n".join(paragraphs).strip()
    except zipfile.BadZipFile:
        fail("DOCX 文件无法读取，可能不是有效的 Word 文档。")
    except ElementTree.ParseError:
        fail("DOCX XML 解析失败，请换一个文档重试。")
    if not text:
        fail("DOCX 中没有提取到可制卡文本。")
    return text


def read_epub_document(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            html_names = [
                name
                for name in archive.namelist()
                if name.lower().endswith((".xhtml", ".html", ".htm")) and not name.lower().endswith("nav.xhtml")
            ]
            html_names.sort()
            parts: list[str] = []
            for name in html_names:
                raw = archive.read(name)
                markup = raw.decode("utf-8", errors="replace")
                markup = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", markup)
                markup = re.sub(r"(?i)</(p|div|h[1-6]|li|section|article|br)>", "\n", markup)
                text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", markup))
                text = re.sub(r"[ \t]+", " ", text)
                text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()
                if text:
                    parts.append(text)
            extracted = "\n\n".join(parts).strip()
    except zipfile.BadZipFile:
        fail("EPUB 文件无法读取，可能不是有效的 EPUB。")
    if not extracted:
        fail("EPUB 中没有提取到可制卡文本。")
    return extracted


def read_pdf_document(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        fail("PDF 解析需要 pypdf。请先安装 workers/requirements.txt 里的依赖后重试。")
    try:
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        fail(f"PDF 解析失败：{exc}")
    text = "\n\n".join(page.strip() for page in pages if page.strip()).strip()
    if not text:
        fail("PDF 中没有提取到可制卡文本，可能是扫描版图片 PDF。")
    return text

