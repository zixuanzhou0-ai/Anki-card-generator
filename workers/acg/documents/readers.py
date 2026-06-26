from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from acg.protocol import fail


def hidden_subprocess_flags() -> dict[str, int]:
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


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
    if suffix in {".azw", ".azw3", ".mobi", ".kindle"}:
        return read_kindle_document(document_path)
    fail("暂不支持这个文档格式。请使用 TXT、Markdown、DOCX、EPUB 或 PDF。")


def read_kindle_document(path: Path) -> str:
    converter = shutil.which("ebook-convert")
    if not converter:
        fail(
            "暂不直接读取 Kindle/AZW3/MOBI 电子书：没有检测到 Calibre 的 ebook-convert。"
            "请先用 Calibre 转成 EPUB，或安装 Calibre 并确保 ebook-convert 在 PATH 中，"
            "再在文档资料里选择 .azw3/.mobi 文件。"
        )
    with tempfile.TemporaryDirectory(prefix="anki_card_ebook_") as tmp:
        epub_path = Path(tmp) / f"{path.stem}.epub"
        try:
            subprocess.run(
                [converter, str(path), str(epub_path)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=180,
                **hidden_subprocess_flags(),
            )
        except subprocess.TimeoutExpired:
            fail("Kindle/AZW3/MOBI 转 EPUB 超时。请先用 Calibre 手动转成 EPUB 后再导入。")
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            suffix = f"：{detail[:300]}" if detail else "。"
            fail(f"Kindle/AZW3/MOBI 转 EPUB 失败{suffix}请先用 Calibre 手动转成 EPUB 后再导入。")
        if not epub_path.exists() or epub_path.stat().st_size == 0:
            fail("Kindle/AZW3/MOBI 转 EPUB 后没有生成有效文件。请先用 Calibre 手动转成 EPUB 后再导入。")
        return read_epub_document(epub_path)


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
