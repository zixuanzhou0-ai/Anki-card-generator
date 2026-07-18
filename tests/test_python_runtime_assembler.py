from __future__ import annotations

from pathlib import Path

import pytest

from card_service.python_runtime_assembler import (
    BUILD_METADATA_NAME,
    PythonRuntimeAssemblyError,
    PythonRuntimeIdentity,
    assemble_python_runtime,
)
from card_service.python_runtime_lock import generate_requirements_lock
from tests.test_python_runtime_lock import wheel


IDENTITY = PythonRuntimeIdentity("cpython", "3.13.12", "amd64")


def fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "source-python"
    (source / "Lib" / "site-packages").mkdir(parents=True)
    (source / "Lib" / "os.py").write_text("name = 'nt'\n", encoding="utf-8")
    (source / "Lib" / "site-packages" / "ambient.py").write_text("SECRET = True\n", encoding="utf-8")
    (source / "Scripts").mkdir()
    (source / "Scripts" / "pip.exe").write_bytes(b"ambient-pip")
    (source / "DLLs").mkdir()
    (source / "DLLs" / "_socket.pyd").write_bytes(b"socket")
    (source / "python.exe").write_bytes(b"python")
    (source / "python313.dll").write_bytes(b"dll")
    (source / "ffmpeg.exe").write_bytes(b"ambient-ffmpeg")
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("example==1.0\n", encoding="utf-8")
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    wheel(
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
    return source.resolve(), lock.resolve(), wheelhouse.resolve()


def fake_installer(_python: Path, target: Path, _lock: Path, _wheelhouse: Path) -> None:
    package = target / "Lib" / "site-packages" / "example"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("__version__ = '1.0'\n", encoding="utf-8")


def test_assembler_excludes_ambient_packages_and_tools_and_publishes_atomically(tmp_path: Path) -> None:
    source, lock, wheelhouse = fixture(tmp_path)
    output = (tmp_path / "portable-python").resolve()
    result = assemble_python_runtime(
        source,
        output,
        lock_path=lock,
        wheelhouse=wheelhouse,
        expected_version="3.13.12",
        probe=lambda _path: IDENTITY,
        installer=fake_installer,
    )

    assert result.identity == IDENTITY
    assert result.wheel_count == 1
    assert (output / "python.exe").is_file()
    assert (output / "Lib" / "os.py").is_file()
    assert (output / "Lib" / "site-packages" / "example" / "__init__.py").is_file()
    assert not (output / "Lib" / "site-packages" / "ambient.py").exists()
    assert not (output / "Scripts").exists()
    assert not (output / "ffmpeg.exe").exists()
    metadata = (output / BUILD_METADATA_NAME).read_text(encoding="utf-8")
    assert '"networkUsedDuringAssembly":false' in metadata
    assert str(source) not in metadata
    assert str(wheelhouse) not in metadata


def test_assembler_rejects_identity_mismatch_before_copy(tmp_path: Path) -> None:
    source, lock, wheelhouse = fixture(tmp_path)
    output = (tmp_path / "portable-python").resolve()
    with pytest.raises(PythonRuntimeAssemblyError) as caught:
        assemble_python_runtime(
            source,
            output,
            lock_path=lock,
            wheelhouse=wheelhouse,
            expected_version="3.13.11",
            probe=lambda _path: IDENTITY,
            installer=fake_installer,
        )
    assert caught.value.code == "PYTHON_RUNTIME_IDENTITY_MISMATCH"
    assert not output.exists()


def test_assembler_rejects_changed_wheel_and_preserves_existing_output(tmp_path: Path) -> None:
    source, lock, wheelhouse = fixture(tmp_path)
    wheel_path = next(wheelhouse.glob("*.whl"))
    wheel_path.write_bytes(wheel_path.read_bytes() + b"changed")
    output = (tmp_path / "portable-python").resolve()
    with pytest.raises(PythonRuntimeAssemblyError) as changed:
        assemble_python_runtime(
            source,
            output,
            lock_path=lock,
            wheelhouse=wheelhouse,
            expected_version="3.13.12",
            probe=lambda _path: IDENTITY,
            installer=fake_installer,
        )
    assert changed.value.code == "PYTHON_LOCK_WHEELHOUSE_MISMATCH"
    assert not output.exists()

    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(PythonRuntimeAssemblyError) as existing:
        assemble_python_runtime(
            source,
            output,
            lock_path=lock,
            wheelhouse=wheelhouse,
            expected_version="3.13.12",
            probe=lambda _path: IDENTITY,
            installer=fake_installer,
        )
    assert existing.value.code == "PYTHON_RUNTIME_OUTPUT_EXISTS"
    assert marker.read_text(encoding="utf-8") == "keep"


def test_assembler_rejects_post_copy_identity_change(tmp_path: Path) -> None:
    source, lock, wheelhouse = fixture(tmp_path)
    identities = iter(
        [
            IDENTITY,
            PythonRuntimeIdentity("cpython", "3.13.12", "arm64"),
        ]
    )
    with pytest.raises(PythonRuntimeAssemblyError) as caught:
        assemble_python_runtime(
            source,
            (tmp_path / "portable-python").resolve(),
            lock_path=lock,
            wheelhouse=wheelhouse,
            expected_version="3.13.12",
            probe=lambda _path: next(identities),
            installer=fake_installer,
        )
    assert caught.value.code == "PYTHON_RUNTIME_IDENTITY_MISMATCH"


def test_assembler_rejects_generated_bytecode_from_an_installed_wheel(tmp_path: Path) -> None:
    source, lock, wheelhouse = fixture(tmp_path)
    output = (tmp_path / "portable-python").resolve()

    def bytecode_installer(_python: Path, target: Path, _lock: Path, _wheelhouse: Path) -> None:
        cache = target / "Lib" / "site-packages" / "example" / "__pycache__"
        cache.mkdir(parents=True)
        (cache / "__init__.cpython-313.pyc").write_bytes(b"generated")

    with pytest.raises(PythonRuntimeAssemblyError) as caught:
        assemble_python_runtime(
            source,
            output,
            lock_path=lock,
            wheelhouse=wheelhouse,
            expected_version="3.13.12",
            probe=lambda _path: IDENTITY,
            installer=bytecode_installer,
        )
    assert caught.value.code == "PYTHON_RUNTIME_BYTECODE_PRESENT"
    assert not output.exists()
