from __future__ import annotations

import re
import subprocess
import sys
from enum import Enum
from functools import partial
from os import PathLike
from typing import Final, TypeVar, Union, cast

from anyio import CapacityLimiter, create_task_group, to_process
from anyio import Path as AsyncPath
from PIL.Image import Image

from kreuzberg import ExtractionResult, ParsingError
from kreuzberg._constants import DEFAULT_MAX_PROCESSES
from kreuzberg._mime_types import PLAIN_TEXT_MIME_TYPE
from kreuzberg._string import normalize_spaces
from kreuzberg._sync import run_sync
from kreuzberg._tmp import create_temp_file
from kreuzberg.exceptions import MissingDependencyError, OCRError

if sys.version_info < (3, 11):  # pragma: no cover
    from exceptiongroup import ExceptionGroup  # type: ignore[import-not-found]

MINIMAL_SUPPORTED_TESSERACT_VERSION: Final[int] = 5

version_ref = {"checked": False}

T = TypeVar("T", bound=Union[Image, PathLike[str], str])


class PSMMode(Enum):
    """Enum for Tesseract Page Segmentation Modes (PSM) with human-readable values."""

    OSD_ONLY = 0
    """Orientation and script detection only."""
    AUTO_OSD = 1
    """Automatic page segmentation with orientation and script detection."""
    AUTO_ONLY = 2
    """Automatic page segmentation without OSD."""
    AUTO = 3
    """Fully automatic page segmentation (default)."""
    SINGLE_COLUMN = 4
    """Assume a single column of text."""
    SINGLE_BLOCK_VERTICAL = 5
    """Assume a single uniform block of vertically aligned text."""
    SINGLE_BLOCK = 6
    """Assume a single uniform block of text."""
    SINGLE_LINE = 7
    """Treat the image as a single text line."""
    SINGLE_WORD = 8
    """Treat the image as a single word."""
    CIRCLE_WORD = 9
    """Treat the image as a single word in a circle."""
    SINGLE_CHAR = 10
    """Treat the image as a single character."""


async def validate_tesseract_version() -> None:
    """Validate that Tesseract is installed and is version 5 or above.

    Raises:
        MissingDependencyError: If Tesseract is not installed or is below version 5.
    """
    try:
        if version_ref["checked"]:
            return

        command = ["tesseract", "--version"]
        result = await run_sync(subprocess.run, command, capture_output=True)
        version_match = re.search(r"tesseract\s+v?(\d+)", result.stdout.decode())
        if not version_match or int(version_match.group(1)) < MINIMAL_SUPPORTED_TESSERACT_VERSION:
            raise MissingDependencyError("Tesseract version 5 or above is required.")

        version_ref["checked"] = True
    except FileNotFoundError as e:
        raise MissingDependencyError("Tesseract is not installed.") from e


async def process_file(
    input_file: str | PathLike[str],
    *,
    language: str,
    psm: PSMMode,
    max_processes: int = DEFAULT_MAX_PROCESSES,
) -> ExtractionResult:
    """Process a single image file using Tesseract OCR.

    Args:
        input_file: The path to the image file to process.
        language: The language code for OCR.
        psm: Page segmentation mode.
        max_processes: Maximum number of concurrent processes. Defaults to CPU count / 2 (minimum 1).

    Raises:
        OCRError: If OCR fails to extract text from the image.

    Returns:
        ExtractionResult: The extracted text from the image.
    """
    output_path, unlink = await create_temp_file(".txt")
    try:
        output_base = str(output_path).replace(".txt", "")
        command = [
            "tesseract",
            str(input_file),
            output_base,
            "-l",
            language,
            "--psm",
            str(psm.value),
        ]

        result = await to_process.run_sync(
            partial(subprocess.run, capture_output=True),
            command,
            limiter=CapacityLimiter(max_processes),
            cancellable=True,
        )

        if not result.returncode == 0:
            raise OCRError("OCR failed with a non-0 return code.")

        output = await AsyncPath(output_path).read_text("utf-8")
        return ExtractionResult(content=normalize_spaces(output), mime_type=PLAIN_TEXT_MIME_TYPE, metadata={})
    except (RuntimeError, OSError) as e:
        raise OCRError("Failed to OCR using tesseract") from e
    finally:
        await unlink()


async def process_image(
    image: Image,
    *,
    language: str,
    psm: PSMMode,
    max_processes: int = DEFAULT_MAX_PROCESSES,
) -> ExtractionResult:
    """Process a single Pillow Image using Tesseract OCR.

    Args:
        image: The Pillow Image to process.
        language: The language code for OCR.
        psm: Page segmentation mode.
        max_processes: Maximum number of concurrent processes. Defaults to CPU count / 2 (minimum 1).

    Returns:
        ExtractionResult: The extracted text from the image.
    """
    image_path, unlink = await create_temp_file(".png")
    await run_sync(image.save, str(image_path), format="PNG")
    result = await process_file(image_path, language=language, psm=psm, max_processes=max_processes)
    await unlink()
    return result


async def process_image_with_tesseract(
    image: Image | PathLike[str] | str,
    *,
    language: str = "eng",
    psm: PSMMode = PSMMode.AUTO,
    max_processes: int = DEFAULT_MAX_PROCESSES,
) -> ExtractionResult:
    """Run Tesseract OCR asynchronously on a single Pillow Image or a list of Pillow Images.

    Args:
        image: A single Pillow Image, a pathlike or a string or a list of Pillow Images to process.
        language: The language code for OCR (default: "eng").
        psm: Page segmentation mode (default: PSMMode.AUTO).
        max_processes: Maximum number of concurrent processes. Defaults to CPU count / 2 (minimum 1).

    Raises:
        ValueError: If the input is not a Pillow Image or a list of Pillow Images.

    Returns:
        Extracted text as a string
    """
    await validate_tesseract_version()

    if isinstance(image, Image):
        return await process_image(image, language=language, psm=psm, max_processes=max_processes)

    if isinstance(image, (PathLike, str)):
        return await process_file(image, language=language, psm=psm, max_processes=max_processes)

    raise ValueError("Input must be one of: str, Pathlike or Pillow Image.")


async def batch_process_images(
    images: list[T],
    *,
    language: str = "eng",
    psm: PSMMode = PSMMode.AUTO,
    max_processes: int = DEFAULT_MAX_PROCESSES,
) -> list[ExtractionResult]:
    """Run Tesseract OCR asynchronously on multiple images with controlled concurrency.

    Args:
        images: A list of Pillow Images, paths or strings to process.
        language: The language code for OCR (default: "eng").
        psm: Page segmentation mode (default: PSMMode.AUTO).
        max_processes: Maximum number of concurrent processes. Defaults to CPU count / 2 (minimum 1).

    Raises:
        ParsingError: If OCR fails to extract text from any of the images.

    Returns:
        List of ExtractionResult objects, one per input image.
    """
    await validate_tesseract_version()
    results = cast(list[ExtractionResult], list(range(len(images))))

    async def _process_image(index: int, image: T) -> None:
        results[index] = await process_image_with_tesseract(
            image, language=language, psm=psm, max_processes=max_processes
        )

    try:
        async with create_task_group() as tg:
            for i, image in enumerate(images):
                tg.start_soon(_process_image, i, image)
        return results
    except ExceptionGroup as eg:
        raise ParsingError("Failed to process images with Tesseract") from eg
