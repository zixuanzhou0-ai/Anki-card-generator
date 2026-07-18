from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from card_service.python_runtime_lock import (
    PythonRuntimeLockError,
    generate_requirements_lock,
    inspect_wheel,
    parse_requirements_lock,
    verify_wheelhouse_against_lock,
)

ROOT = Path(__file__).resolve().parents[1]

def wheel(
    root: Path,
    *,
    filename: str,
    name: str,
    version: str,
    tag: str = "py3-none-any",
    metadata_padding: int = 0,
) -> Path:
    path = root / filename
    dist_info = f"{name.replace('-', '_')}-{version}.dist-info"
    metadata = f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n\n".encode()
    metadata += b"x" * metadata_padding
    descriptor = f"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: {tag}\n\n"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(f"{dist_info}/METADATA", metadata)
        archive.writestr(f"{dist_info}/WHEEL", descriptor)
        archive.writestr(f"{name}/__init__.py", "")
    return path


def test_lock_is_deterministic_and_pins_roots_transitives_and_hashes(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "example[beta,alpha]==1.2.3\n# comment\ndirect==2.0\n",
        encoding="utf-8",
    )
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    example = wheel(
        wheelhouse,
        filename="example-1.2.3-py3-none-any.whl",
        name="example",
        version="1.2.3",
    )
    direct = wheel(
        wheelhouse,
        filename="direct-2.0-py3-none-any.whl",
        name="direct",
        version="2.0",
    )
    transitive = wheel(
        wheelhouse,
        filename="transitive_dep-4.5-py3-none-any.whl",
        name="transitive-dep",
        version="4.5",
    )

    first = generate_requirements_lock(
        requirements.resolve(),
        wheelhouse.resolve(),
        python_version="3.13",
        abi="cp313",
        platform_tag="win_amd64",
    )
    second = generate_requirements_lock(
        requirements.resolve(),
        wheelhouse.resolve(),
        python_version="3.13",
        abi="cp313",
        platform_tag="win_amd64",
    )

    assert first == second
    assert f"example[alpha,beta]==1.2.3 --hash=sha256:{hashlib.sha256(example.read_bytes()).hexdigest()}" in first
    assert f"direct==2.0 --hash=sha256:{hashlib.sha256(direct.read_bytes()).hexdigest()}" in first
    assert (
        f"transitive-dep==4.5 --hash=sha256:{hashlib.sha256(transitive.read_bytes()).hexdigest()}"
        in first
    )
    assert first.index("direct==") < first.index("example[") < first.index("transitive-dep==")


def test_wheel_inspection_uses_metadata_identity_and_compatibility_tags(tmp_path: Path) -> None:
    path = wheel(
        tmp_path,
        filename="demo-1.0-cp313-cp313-win_amd64.whl",
        name="Demo_Package",
        version="1.0",
        tag="cp313-cp313-win_amd64",
    )
    inspected = inspect_wheel(path.resolve())
    assert inspected.name == "Demo_Package"
    assert inspected.normalized_name == "demo-package"
    assert inspected.version == "1.0"
    assert inspected.tags == ("cp313-cp313-win_amd64",)


def test_lock_rejects_root_version_mismatch_duplicate_packages_and_non_wheels(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("example==1.0\n", encoding="utf-8")
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    wheel(
        wheelhouse,
        filename="example-2.0-py3-none-any.whl",
        name="example",
        version="2.0",
    )
    with pytest.raises(PythonRuntimeLockError) as mismatch:
        generate_requirements_lock(
            requirements.resolve(),
            wheelhouse.resolve(),
            python_version="3.13",
            abi="cp313",
            platform_tag="win_amd64",
        )
    assert mismatch.value.code == "PYTHON_LOCK_ROOT_MISMATCH"

    wheel(
        wheelhouse,
        filename="example_alias-2.0-py3-none-any.whl",
        name="Example",
        version="2.0",
    )
    with pytest.raises(PythonRuntimeLockError) as duplicate:
        generate_requirements_lock(
            requirements.resolve(),
            wheelhouse.resolve(),
            python_version="3.13",
            abi="cp313",
            platform_tag="win_amd64",
        )
    assert duplicate.value.code == "PYTHON_LOCK_WHEEL_DUPLICATE"

    (wheelhouse / "notes.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(PythonRuntimeLockError) as unexpected:
        generate_requirements_lock(
            requirements.resolve(),
            wheelhouse.resolve(),
            python_version="3.13",
            abi="cp313",
            platform_tag="win_amd64",
        )
    assert unexpected.value.code == "PYTHON_LOCK_WHEELHOUSE_INVALID"


@pytest.mark.parametrize(
    "requirement",
    [
        "example>=1.0",
        "example==1.0; python_version > '3'",
        "--index-url https://example.invalid",
        "example",
    ],
)
def test_root_requirements_must_be_exact_and_marker_free(tmp_path: Path, requirement: str) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(requirement + "\n", encoding="utf-8")
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    wheel(
        wheelhouse,
        filename="example-1.0-py3-none-any.whl",
        name="example",
        version="1.0",
    )
    with pytest.raises(PythonRuntimeLockError) as caught:
        generate_requirements_lock(
            requirements.resolve(),
            wheelhouse.resolve(),
            python_version="3.13",
            abi="cp313",
            platform_tag="win_amd64",
        )
    assert caught.value.code == "PYTHON_LOCK_REQUIREMENTS_INVALID"


def test_wheel_metadata_is_bounded_before_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import card_service.python_runtime_lock as lock_module

    path = wheel(
        tmp_path,
        filename="example-1.0-py3-none-any.whl",
        name="example",
        version="1.0",
        metadata_padding=128,
    )
    monkeypatch.setattr(lock_module, "MAX_WHEEL_METADATA_BYTES", 64)
    with pytest.raises(PythonRuntimeLockError) as caught:
        inspect_wheel(path.resolve())
    assert caught.value.code == "PYTHON_LOCK_WHEEL_INVALID"


def test_lock_verifier_requires_the_exact_wheel_set_versions_and_hashes(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("example==1.0\n", encoding="utf-8")
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    path = wheel(
        wheelhouse,
        filename="example-1.0-py3-none-any.whl",
        name="example",
        version="1.0",
    )
    lock = tmp_path / "requirements.lock"
    lock.write_text(
        generate_requirements_lock(
            requirements.resolve(),
            wheelhouse.resolve(),
            python_version="3.13",
            abi="cp313",
            platform_tag="win_amd64",
        ),
        encoding="utf-8",
    )
    assert verify_wheelhouse_against_lock(lock.resolve(), wheelhouse.resolve())["example"].sha256

    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(PythonRuntimeLockError) as changed:
        verify_wheelhouse_against_lock(lock.resolve(), wheelhouse.resolve())
    assert changed.value.code == "PYTHON_LOCK_WHEELHOUSE_MISMATCH"


def test_committed_windows_cp313_lock_is_exact_and_matches_direct_requirements() -> None:
    lock_path = ROOT / "workers" / "requirements-win-cp313.lock"
    locked = parse_requirements_lock(lock_path.resolve())
    assert len(locked) == 25
    assert locked["genanki"].version == "0.13.1"
    assert locked["yt-dlp"].version == "2026.7.4"
    assert locked["pypdf"].version == "6.14.2"
    assert locked["cryptography"].version == "49.0.0"
    assert all(len(requirement.sha256) == 64 for requirement in locked.values())
