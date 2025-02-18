from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from kreuzberg import ExtractionResult
from kreuzberg._pandoc import (
    MIMETYPE_TO_PANDOC_TYPE_MAPPING,
    _get_pandoc_type_from_mime_type,
    _handle_extract_file,
    _handle_extract_metadata,
    _validate_pandoc_version,
    process_content_with_pandoc,
    process_file_with_pandoc,
)
from kreuzberg._tmp import create_temp_file
from kreuzberg.exceptions import MissingDependencyError, ParsingError, ValidationError

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

SAMPLE_PANDOC_JSON = {
    "pandoc-api-version": [1, 23, 1],
    "meta": {"title": {"t": "MetaString", "c": "Test Document"}, "author": {"t": "MetaString", "c": "Test Author"}},
    "blocks": [],
}


@pytest.fixture
def mock_subprocess_run(mocker: MockerFixture) -> Mock:
    def run_sync(command: list[str], **kwargs: Any) -> Mock:
        result = Mock()
        result.returncode = 0
        result.stderr = b""

        if "--version" in command:
            result.stdout = b"pandoc 3.1.0"
            return result

        # Handle error test cases
        if "test_process_file_error" in str(kwargs.get("cwd")):
            result.returncode = 1
            result.stderr = b"Error processing file"
            raise ParsingError("Error processing file", context={"error": "Error processing file"})

        # Handle empty result test case
        if "test_process_content_empty_result" in str(kwargs.get("cwd")):
            result.returncode = 1
            result.stderr = b"Empty content"
            raise ParsingError("Empty content", context={"error": "Empty content"})

        # Handle metadata error test case
        if "test_extract_metadata_error" in str(kwargs.get("cwd")):
            result.returncode = 1
            result.stderr = b"Invalid metadata"
            raise ParsingError("Invalid metadata", context={"error": "Invalid metadata"})

        # Handle runtime error test case
        if "test_process_file_runtime_error" in str(kwargs.get("cwd")):
            raise RuntimeError("Command failed")

        # Normal case
        output_file = next((str(arg) for arg in command if str(arg).endswith((".md", ".json"))), "")
        if output_file:
            content = (
                json.dumps(SAMPLE_PANDOC_JSON) if str(output_file).endswith(".json") else "Sample processed content"
            )
            Path(output_file).write_text(content)
        return result

    # Mock anyio.run_process
    mock = mocker.patch("anyio.run_process", side_effect=run_sync)
    return mock


@pytest.fixture
def mock_subprocess_run_invalid(mocker: MockerFixture) -> Mock:
    def run_sync(command: list[str], **kwargs: Any) -> Mock:
        result = Mock()
        result.stdout = b"pandoc 1.0.0"
        result.returncode = 0
        result.stderr = b""
        return result

    mock = mocker.patch("anyio.run_process", side_effect=run_sync)
    return mock


@pytest.fixture
def mock_subprocess_run_error(mocker: MockerFixture) -> Mock:
    def run_sync(command: list[str], **kwargs: Any) -> Mock:
        raise FileNotFoundError

    mock = mocker.patch("anyio.run_process", side_effect=run_sync)
    return mock


@pytest.fixture(autouse=True)
def reset_version_ref(mocker: MockerFixture) -> None:
    mocker.patch("kreuzberg._pandoc.version_ref", {"checked": False})


@pytest.mark.anyio
async def test_validate_pandoc_version(mock_subprocess_run: Mock) -> None:
    await _validate_pandoc_version()
    mock_subprocess_run.assert_called_with(["pandoc", "--version"])


@pytest.mark.anyio
async def test_validate_pandoc_version_invalid(mock_subprocess_run_invalid: Mock) -> None:
    with pytest.raises(MissingDependencyError, match="Pandoc version 3 or above is required"):
        await _validate_pandoc_version()


@pytest.mark.anyio
async def test_validate_pandoc_version_missing(mock_subprocess_run_error: Mock) -> None:
    with pytest.raises(MissingDependencyError, match="Pandoc is not installed"):
        await _validate_pandoc_version()


@pytest.mark.anyio
async def test_get_pandoc_type_from_mime_type_valid() -> None:
    for mime_type in MIMETYPE_TO_PANDOC_TYPE_MAPPING:
        extension = _get_pandoc_type_from_mime_type(mime_type)
        assert isinstance(extension, str)
        assert extension


@pytest.mark.anyio
async def test_get_pandoc_type_from_mime_type_invalid() -> None:
    with pytest.raises(ValidationError, match="Unsupported mime type"):
        _get_pandoc_type_from_mime_type("invalid/mime-type")


@pytest.mark.anyio
async def test_process_file_success(mock_subprocess_run: Mock, docx_document: Path) -> None:
    result = await process_file_with_pandoc(
        docx_document, mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert isinstance(result, ExtractionResult)
    assert result.content.strip() == "Sample processed content"


@pytest.mark.anyio
async def test_process_file_error(mock_subprocess_run: Mock, docx_document: Path) -> None:
    def side_effect(*args: list[Any], **_: Any) -> Mock:
        if args[0][0] == "pandoc" and "--version" in args[0]:
            mock_subprocess_run.return_value.stdout = b"pandoc 3.1.0"
            return cast(Mock, mock_subprocess_run.return_value)
        mock_subprocess_run.return_value.returncode = 1
        mock_subprocess_run.return_value.stderr = b"Error processing file"
        raise RuntimeError("Error processing file")

    mock_subprocess_run.side_effect = side_effect
    with pytest.raises(ParsingError, match="Failed to extract file data"):
        await process_file_with_pandoc(
            docx_document, mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )


@pytest.mark.anyio
async def test_process_content_success(mock_subprocess_run: Mock) -> None:
    result = await process_content_with_pandoc(
        b"test content", mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert isinstance(result, ExtractionResult)
    assert result.content.strip() == "Sample processed content"


@pytest.mark.anyio
async def test_extract_metadata_error(mock_subprocess_run: Mock, docx_document: Path) -> None:
    def side_effect(*args: list[Any], **_: Any) -> Mock:
        if args[0][0] == "pandoc" and "--version" in args[0]:
            mock_subprocess_run.return_value.stdout = b"pandoc 3.1.0"
            return cast(Mock, mock_subprocess_run.return_value)
        mock_subprocess_run.return_value.returncode = 1
        mock_subprocess_run.return_value.stderr = b"Error extracting metadata"
        raise RuntimeError("Error extracting metadata")

    mock_subprocess_run.side_effect = side_effect
    with pytest.raises(ParsingError, match="Failed to extract file data"):
        await _handle_extract_metadata(
            docx_document, mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )


@pytest.mark.anyio
async def test_extract_metadata_runtime_error(mock_subprocess_run: Mock, docx_document: Path) -> None:
    mock_subprocess_run.side_effect = RuntimeError("Command failed")

    with pytest.raises(ParsingError, match="Failed to extract file data"):
        await _handle_extract_metadata(
            docx_document, mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )


@pytest.mark.anyio
async def test_integration_validate_pandoc_version() -> None:
    await _validate_pandoc_version()


@pytest.mark.anyio
async def test_integration_process_file(markdown_document: Path) -> None:
    result = await process_file_with_pandoc(markdown_document, mime_type="text/x-markdown")
    assert isinstance(result, ExtractionResult)
    assert isinstance(result.content, str)
    assert result.content.strip()


@pytest.mark.anyio
async def test_integration_process_content() -> None:
    content = b"# Test\nThis is a test file."
    result = await process_content_with_pandoc(content, mime_type="text/x-markdown")
    assert isinstance(result, ExtractionResult)
    assert isinstance(result.content, str)
    assert result.content.strip()


@pytest.mark.anyio
async def test_integration_extract_metadata(markdown_document: Path) -> None:
    result = await _handle_extract_metadata(markdown_document, mime_type="text/x-markdown")
    assert isinstance(result, dict)


@pytest.mark.anyio
async def test_process_file_runtime_error(mock_subprocess_run: Mock, docx_document: Path) -> None:
    def side_effect(*args: list[Any], **_: Any) -> Mock:
        if args[0][0] == "pandoc" and "--version" in args[0]:
            mock_subprocess_run.return_value.stdout = b"pandoc 3.1.0"
            return cast(Mock, mock_subprocess_run.return_value)
        raise RuntimeError("Pandoc error")

    mock_subprocess_run.side_effect = side_effect
    with pytest.raises(ParsingError, match="Failed to extract file data"):
        await process_file_with_pandoc(
            docx_document, mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )


@pytest.mark.anyio
async def test_process_content_empty_result(mock_subprocess_run: Mock) -> None:
    def side_effect(*args: list[Any], **_: Any) -> Mock:
        if args[0][0] == "pandoc" and "--version" in args[0]:
            mock_subprocess_run.return_value.stdout = b"pandoc 3.1.0"
            return cast(Mock, mock_subprocess_run.return_value)
        output_file = next((str(arg) for arg in args[0] if str(arg).endswith((".md", ".json"))), "")
        if output_file:
            if str(output_file).endswith(".json"):
                Path(output_file).write_text('{"pandoc-api-version":[1,22,2,1],"meta":{},"blocks":[]}')
            else:
                Path(output_file).write_text("")
            mock_subprocess_run.return_value.returncode = 0
            return cast(Mock, mock_subprocess_run.return_value)
        raise RuntimeError("Empty content")

    mock_subprocess_run.side_effect = side_effect
    result = await process_content_with_pandoc(
        b"content", mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert isinstance(result, ExtractionResult)
    assert result.content == ""
    assert result.metadata == {}


@pytest.mark.anyio
async def test_process_file_invalid_mime_type(mock_subprocess_run: Mock, docx_document: Path) -> None:
    with pytest.raises(ValidationError, match="Unsupported mime type"):
        await process_file_with_pandoc(docx_document, mime_type="invalid/mime-type")


@pytest.mark.anyio
async def test_process_content_invalid_mime_type(mock_subprocess_run: Mock) -> None:
    with pytest.raises(ValidationError, match="Unsupported mime type"):
        await process_content_with_pandoc(b"content", mime_type="invalid/mime-type")


@pytest.mark.anyio
async def test_handle_extract_metadata_os_error(
    mock_subprocess_run: Mock, mocker: MockerFixture, docx_document: Path
) -> None:
    await create_temp_file(".json")
    mock_path = Mock(read_text=AsyncMock(side_effect=OSError))

    mocker.patch("kreuzberg._pandoc.AsyncPath", return_value=mock_path)
    with pytest.raises(ParsingError) as exc_info:
        await _handle_extract_metadata(
            docx_document, mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    assert "Failed to extract file data" in str(exc_info.value)


@pytest.mark.anyio
async def test_handle_extract_file_os_error(
    mock_subprocess_run: Mock, mocker: MockerFixture, docx_document: Path
) -> None:
    await create_temp_file(".md")
    mock_path = Mock(read_text=AsyncMock(side_effect=OSError))

    mocker.patch("kreuzberg._pandoc.AsyncPath", return_value=mock_path)
    with pytest.raises(ParsingError) as exc_info:
        await _handle_extract_file(
            docx_document, mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    assert "Failed to extract file data" in str(exc_info.value)
