"""Tests for GMFT table extraction functionality."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from PIL import Image

from kreuzberg import ExtractionConfig, GMFTConfig
from kreuzberg._gmft import extract_tables
from kreuzberg.exceptions import MissingDependencyError
from kreuzberg.extraction import extract_file
from tests.conftest import pdfs_with_tables


@pytest.fixture
def mock_cropped_table() -> MagicMock:
    """Mock for GMFT CroppedTable."""
    mock = MagicMock()
    mock.page.page_number = 1
    mock.image.return_value = Image.new("RGB", (100, 100))
    return mock


@pytest.fixture
def mock_formatted_table() -> MagicMock:
    """Mock for GMFT FormattedTable."""
    mock = MagicMock()
    df = pd.DataFrame({"Column1": [1, 2, 3], "Column2": ["A", "B", "C"]})
    mock.df = AsyncMock(return_value=df)
    return mock


@pytest.mark.anyio
async def test_extract_tables_with_default_config() -> None:
    """Test extracting tables with default configuration."""
    pdf_path = pdfs_with_tables[0]

    try:
        tables = await extract_tables(pdf_path)

        assert tables
        assert isinstance(tables, list)
        assert all(isinstance(table, dict) for table in tables)

        for table in tables:
            assert "page_number" in table
            assert isinstance(table["page_number"], int)
            assert "text" in table
            assert isinstance(table["text"], str)
            assert "df" in table
            assert isinstance(table["df"], pd.DataFrame)
            assert "cropped_image" in table
            assert isinstance(table["cropped_image"], Image.Image)
    except MissingDependencyError:
        pytest.skip("GMFT dependency not installed")


@pytest.mark.anyio
async def test_gmft_integration_with_extraction_api() -> None:
    """Test integration of GMFT with the main extraction API."""
    pdf_path = pdfs_with_tables[0]

    try:
        config = ExtractionConfig(
            extract_tables=True, gmft_config=GMFTConfig(detector_base_threshold=0.8, enable_multi_header=True)
        )

        result = await extract_file(pdf_path, config=config)

        assert hasattr(result, "tables")
        assert result.tables
        assert isinstance(result.tables, list)

        for table in result.tables:
            assert "page_number" in table
            assert "text" in table
            assert "df" in table
            assert "cropped_image" in table

            assert "|" in table["text"]

            assert not table["df"].empty

    except MissingDependencyError:
        pytest.skip("GMFT dependency not installed")


@pytest.mark.anyio
async def test_extract_tables_with_custom_config() -> None:
    """Test extracting tables with custom configuration."""
    pdf_path = pdfs_with_tables[0]

    config = GMFTConfig(detector_base_threshold=0.85, remove_null_rows=True, enable_multi_header=True, verbosity=1)

    try:
        tables = await extract_tables(pdf_path, config)

        assert tables
        assert isinstance(tables, list)
    except MissingDependencyError:
        pytest.skip("GMFT dependency not installed")


@pytest.mark.anyio
async def test_extract_tables_missing_dependency() -> None:
    """Test MissingDependencyError when GMFT is not installed."""
    with patch("kreuzberg._gmft.run_sync", side_effect=ImportError("No module named 'gmft'")):
        with pytest.raises(MissingDependencyError) as exc_info:
            await extract_tables("dummy_path.pdf")

        assert "table extraction" in str(exc_info.value)
        assert "gmft" in str(exc_info.value)


@pytest.mark.anyio
async def test_extract_tables_with_mocks() -> None:
    """Test extract_tables with mocked GMFT components."""

    mock_path = MagicMock(spec=Path)

    mock_doc = MagicMock()
    mock_page = MagicMock()
    mock_doc.__iter__.return_value = [mock_page]
    mock_doc.close = MagicMock()

    mock_cropped_table = MagicMock()
    mock_cropped_table.page.page_number = 1
    mock_cropped_table.image.return_value = Image.new("RGB", (100, 100))

    mock_formatted_table = MagicMock()
    mock_df = pd.DataFrame({"Col1": [1, 2], "Col2": ["A", "B"]})
    mock_formatted_table.df = AsyncMock(return_value=mock_df)

    mock_auto = MagicMock()
    mock_auto.AutoTableDetector = MagicMock()
    mock_auto.AutoTableFormatter = MagicMock()
    mock_auto.TATRFormatConfig = MagicMock()
    mock_auto.CroppedTable = MagicMock()

    mock_detector_tatr = MagicMock()
    mock_detector_tatr.TATRDetectorConfig = MagicMock()

    mock_pdf_bindings = MagicMock()
    mock_pdf_bindings.PyPDFium2Document = MagicMock()

    module_patcher = patch.dict(
        "sys.modules",
        {
            "gmft": MagicMock(),
            "gmft.auto": mock_auto,
            "gmft.detectors.tatr": mock_detector_tatr,
            "gmft.pdf_bindings": mock_pdf_bindings,
        },
    )

    mock_detector = mock_auto.AutoTableDetector.return_value
    mock_detector.extract.return_value = [mock_cropped_table]

    mock_formatter = mock_auto.AutoTableFormatter.return_value
    mock_formatter.extract.return_value = mock_formatted_table

    with module_patcher, patch("kreuzberg._gmft.run_sync") as mock_run_sync:
        mock_run_sync.side_effect = [
            mock_doc,
            [mock_cropped_table],
            mock_formatted_table,
            mock_df,
            None,
        ]

        result = await extract_tables(mock_path)

        assert isinstance(result, list)
        assert len(result) == 1

        table_data = result[0]
        assert isinstance(table_data, dict)
        assert table_data["page_number"] == 1
        assert isinstance(table_data["df"], pd.DataFrame)
        assert isinstance(table_data["text"], str)
        assert isinstance(table_data["cropped_image"], Image.Image)

        mock_auto.AutoTableDetector.assert_called_once()
        mock_auto.AutoTableFormatter.assert_called_once()
        mock_detector_tatr.TATRDetectorConfig.assert_called_once()


@pytest.mark.anyio
async def test_gmft_config_default_values() -> None:
    """Test GMFTConfig default values."""
    config = GMFTConfig()

    assert config.verbosity == 0
    assert config.detector_base_threshold == 0.9
    assert config.formatter_base_threshold == 0.3
    assert config.remove_null_rows is True
    assert config.enable_multi_header is False
    assert config.semantic_spanning_cells is False
    assert config.semantic_hierarchical_left_fill == "algorithm"
    assert config.large_table_threshold == 10
    assert config.large_table_row_overlap_threshold == 0.2


@pytest.mark.anyio
async def test_gmft_config_custom_values() -> None:
    """Test GMFTConfig with custom values."""
    custom_confidence = {
        0: 0.4,
        1: 0.4,
        2: 0.4,
        3: 0.4,
        4: 0.6,
        5: 0.6,
        6: 99,
    }

    config = GMFTConfig(
        verbosity=2,
        formatter_base_threshold=0.5,
        cell_required_confidence=custom_confidence,  # type: ignore[arg-type]
        detector_base_threshold=0.8,
        remove_null_rows=False,
        enable_multi_header=True,
        semantic_spanning_cells=True,
        semantic_hierarchical_left_fill="deep",
        large_table_if_n_rows_removed=10,
        large_table_threshold=15,
        large_table_row_overlap_threshold=0.3,
        large_table_maximum_rows=1500,
        force_large_table_assumption=True,
    )

    assert config.verbosity == 2
    assert config.formatter_base_threshold == 0.5
    assert config.cell_required_confidence == custom_confidence
    assert config.detector_base_threshold == 0.8
    assert config.remove_null_rows is False
    assert config.enable_multi_header is True
    assert config.semantic_spanning_cells is True
    assert config.semantic_hierarchical_left_fill == "deep"
    assert config.large_table_if_n_rows_removed == 10
    assert config.large_table_threshold == 15
    assert config.large_table_row_overlap_threshold == 0.3
    assert config.large_table_maximum_rows == 1500
    assert config.force_large_table_assumption is True


@pytest.mark.anyio
async def test_extract_tables_with_custom_config_mocks() -> None:
    """Test extract_tables with custom config and mocked GMFT components."""
    mock_path = MagicMock(spec=Path)

    custom_config = GMFTConfig(detector_base_threshold=0.8, enable_multi_header=True, semantic_spanning_cells=True)

    mock_auto = MagicMock()
    mock_detector_tatr = MagicMock()
    mock_pdf_bindings = MagicMock()

    module_patcher = patch.dict(
        "sys.modules",
        {
            "gmft": MagicMock(),
            "gmft.auto": mock_auto,
            "gmft.detectors.tatr": mock_detector_tatr,
            "gmft.pdf_bindings": mock_pdf_bindings,
        },
    )

    mock_doc = MagicMock()
    mock_doc.__iter__.return_value = [MagicMock()]

    mock_cropped_table = MagicMock()
    mock_cropped_table.page.page_number = 2
    mock_cropped_table.image.return_value = Image.new("RGB", (100, 100))

    mock_formatted_table = MagicMock()
    mock_df = pd.DataFrame({"Col1": [1, 2], "Col2": ["A", "B"]})

    with module_patcher, patch("kreuzberg._gmft.run_sync") as mock_run_sync:
        mock_run_sync.side_effect = [mock_doc, [mock_cropped_table], mock_formatted_table, mock_df, None]

        await extract_tables(mock_path, custom_config)

        mock_detector_tatr.TATRDetectorConfig.assert_called_once_with(detector_base_threshold=0.8)

        assert mock_auto.TATRFormatConfig.call_args is not None
        format_config_kwargs = mock_auto.TATRFormatConfig.call_args.kwargs
        assert format_config_kwargs["enable_multi_header"] is True
        assert format_config_kwargs["semantic_spanning_cells"] is True
