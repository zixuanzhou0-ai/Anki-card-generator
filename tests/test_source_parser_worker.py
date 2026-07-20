from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pypdf
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from card_service.service import CardService
from card_service.source_inspection import StructuredSourceParserError, _text_nodes
from card_service.windows_sandbox_acl import WindowsSandboxAclError
from workers.acg import source_parser_worker


ROOT = Path(__file__).resolve().parents[1]


def pdf_bytes(*texts: str) -> bytes:
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        font_ref = writer._add_object(font)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): font_ref}
                )
            }
        )
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(
            f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1")
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_pdf_worker_extracts_ordered_bounded_pages(tmp_path: Path) -> None:
    path = tmp_path / "source.pdf"
    path.write_bytes(pdf_bytes("Reliable learning", "Recall first then verify"))

    result = source_parser_worker.parse_pdf(
        path,
        maximum_pages=512,
        maximum_text_bytes=8 * 1024 * 1024,
    )

    assert result["schema"] == "study.source-parser-result"
    assert result["status"] == "conditional"
    assert result["parser"] == {"name": "pypdf", "version": pypdf.__version__}
    assert result["pageCount"] == 2
    assert result["omittedPageCount"] == 0
    assert [page["pageNumber"] for page in result["pages"]] == [1, 2]
    assert [page["text"].strip() for page in result["pages"]] == [
        "Reliable learning",
        "Recall first then verify",
    ]
    assert result["issueCodes"] == ["SOURCE_PDF_LAYOUT_PARTIAL"]


def test_pdf_worker_declares_page_and_text_limits(tmp_path: Path) -> None:
    path = tmp_path / "source.pdf"
    path.write_bytes(pdf_bytes("first page", "second page"))

    result = source_parser_worker.parse_pdf(
        path,
        maximum_pages=1,
        maximum_text_bytes=5,
    )

    assert result["pageCount"] == 2
    assert result["pages"][0]["text"] == "first"
    assert result["pages"][0]["textTruncated"] is True
    assert result["omittedPageCount"] == 1
    assert result["omittedPages"] == [2]
    assert "SOURCE_PDF_PAGE_LIMIT_REACHED" in result["issueCodes"]
    assert "SOURCE_PDF_TEXT_LIMIT_REACHED" in result["issueCodes"]


def test_pdf_worker_blocks_invalid_and_encrypted_documents(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.pdf"
    invalid.write_bytes(b"not a pdf")
    invalid_result = source_parser_worker.parse_pdf(
        invalid,
        maximum_pages=512,
        maximum_text_bytes=8 * 1024 * 1024,
    )
    assert invalid_result["status"] == "blocked"
    assert invalid_result["issueCodes"] == ["SOURCE_PDF_UNREADABLE"]

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("secret")
    encrypted = tmp_path / "encrypted.pdf"
    with encrypted.open("wb") as output:
        writer.write(output)
    encrypted_result = source_parser_worker.parse_pdf(
        encrypted,
        maximum_pages=512,
        maximum_text_bytes=8 * 1024 * 1024,
    )
    assert encrypted_result["status"] == "blocked"
    assert encrypted_result["issueCodes"] == ["SOURCE_PDF_ENCRYPTED"]


def test_pdf_worker_counts_all_omissions_but_bounds_locator_samples(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePage:
        def extract_text(self) -> str:
            return ""

        def get(self, _key: str) -> None:
            return None

    class FakePages:
        def __len__(self) -> int:
            return 1000

        def __getitem__(self, _index: int) -> FakePage:
            return FakePage()

    class FakeReader:
        is_encrypted = False
        pages = FakePages()

    monkeypatch.setattr(pypdf, "PdfReader", lambda *_args, **_kwargs: FakeReader())
    path = tmp_path / "source.pdf"
    path.write_bytes(b"%PDF fake bounded page source")

    result = source_parser_worker.parse_pdf(
        path,
        maximum_pages=1,
        maximum_text_bytes=8 * 1024 * 1024,
    )

    assert result["pageCount"] == 1000
    assert result["omittedPageCount"] == 999
    assert len(result["omittedPages"]) == 256
    assert result["omittedPages"][0] == 2
    assert result["omittedPages"][-1] == 257


def test_text_node_extraction_stops_at_global_limit_without_prebuilding_ranges() -> None:
    nodes, limited = _text_nodes(
        "x\n\n" * 20_001,
        source_id="source-bounded",
        source_type="text",
    )

    assert len(nodes) == 20_000
    assert limited is True


def test_worker_bootstrap_executes_parser_with_text_stdin_contract(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(pdf_bytes("Bootstrap verified"))
    parser_path = ROOT / "workers" / "acg" / "source_parser_worker.py"
    bootstrap_path = ROOT / "card_service" / "worker_bootstrap.py"
    broker_path = ROOT / "workers" / "acg" / "broker_client.py"
    manifest_path = tmp_path / "runtime-manifest.json"
    entries = []
    for resource_id, path in (
        ("managed-python:executable", Path(sys.executable).resolve()),
        ("card-service:worker-bootstrap", bootstrap_path.resolve()),
        ("card-service:broker-client", broker_path.resolve()),
        ("legacy-worker:module:acg/source_parser_worker.py", parser_path.resolve()),
    ):
        data = path.read_bytes()
        import hashlib

        entries.append(
            {
                "resourceId": resource_id,
                "path": str(path),
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    manifest = {"schemaVersion": 1, "entries": entries}
    manifest_source = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    manifest_path.write_bytes(manifest_source)
    import hashlib

    request = {
        "schemaVersion": 1,
        "kind": "pdf",
        "inputName": "source.pdf",
        "limits": {"maximumPages": 512, "maximumTextBytes": 8 * 1024 * 1024},
    }
    process = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(bootstrap_path),
            str(parser_path),
            "parse_source_document",
            hashlib.sha256(parser_path.read_bytes()).hexdigest(),
            str(manifest_path),
            hashlib.sha256(manifest_source).hexdigest(),
        ],
        cwd=tmp_path,
        input=json.dumps({"schemaVersion": 1, "request": request}) + "\n",
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result["status"] == "conditional"
    assert result["pages"][0]["text"].strip() == "Bootstrap verified"


def test_service_maps_acl_failure_to_public_parser_sandbox_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = object.__new__(CardService)

    def fail_parser(**_request: object) -> dict[str, object]:
        raise WindowsSandboxAclError(
            "WINDOWS_ACL_APPLY_FAILED",
            r"sensitive workspace C:\\Users\\person\\AppData\\Local\\Temp\\parser",
        )

    monkeypatch.setattr(service, "_execute_study_source_parser_once", fail_parser)

    with pytest.raises(StructuredSourceParserError) as failed:
        service._execute_study_source_parser(source_ref="artifact:test")

    assert failed.value.code == "SOURCE_PARSER_SANDBOX_UNAVAILABLE"
    assert "sensitive" not in str(failed.value)
