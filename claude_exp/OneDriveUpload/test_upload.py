"""
Tests for upload_to_sharepoint.py

Run all tests:
    pytest test_upload.py -v

Run only unit tests (no real network):
    pytest test_upload.py -v -m unit

Run the integration test (requires real SharePoint credentials in config.json):
    pytest test_upload.py -v -m integration
"""

import json
import re
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import upload_to_sharepoint as usp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{6}$")


def make_dirs(*paths: Path):
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, content: str = "hello world\n"):
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetUniqueName:
    def test_timestamp_appended(self):
        result = usp.get_unique_name("hello.txt")
        assert result.startswith("hello_")
        assert result.endswith(".txt")
        stem_ts = Path(result).stem        # e.g. hello_2026-04-02T221530
        timestamp_part = stem_ts.split("_", 1)[1]
        assert TIMESTAMP_RE.match(timestamp_part), f"Bad timestamp: {timestamp_part}"

    def test_no_extension(self):
        result = usp.get_unique_name("readme")
        assert result.startswith("readme_")
        assert "." not in result

    def test_multiple_dots(self):
        result = usp.get_unique_name("archive.tar.gz")
        assert result.endswith(".gz")
        assert result.startswith("archive.tar_")

    def test_two_calls_differ(self):
        import time
        a = usp.get_unique_name("x.txt")
        time.sleep(1.01)
        b = usp.get_unique_name("x.txt")
        assert a != b


@pytest.mark.unit
class TestLoadConfig:
    def test_loads_keys(self, tmp_path):
        cfg = {
            "sharepoint_url": "https://example.sharepoint.com/sites/s",
            "tenant_id": "tid",
            "client_id": "cid",
            "target_folder": "Documents/uploaded_files",
        }
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
        loaded = usp.load_config(str(cfg_file))
        assert loaded == cfg

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            usp.load_config(str(tmp_path / "nonexistent.json"))


@pytest.mark.unit
class TestRunUnit:
    """Test the full run() flow with SharePoint upload mocked out."""

    @pytest.fixture()
    def workspace(self, tmp_path):
        upload_dir = tmp_path / "upload"
        done_dir = tmp_path / "done"
        make_dirs(upload_dir, done_dir)

        write_text(upload_dir / "hello.txt")

        cfg = {
            "sharepoint_url": "https://example.sharepoint.com/sites/s",
            "tenant_id": "tid",
            "client_id": "cid",
            "target_folder": "Documents/uploaded_files",
        }
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps(cfg), encoding="utf-8")

        return tmp_path, upload_dir, done_dir, cfg_file

    def test_happy_path(self, workspace):
        tmp_path, upload_dir, done_dir, cfg_file = workspace

        with patch.object(usp, "upload_file_to_sharepoint") as mock_upload:
            usp.run(
                input_dir=str(upload_dir),
                done_dir=str(done_dir),
                filename="hello.txt",
                config_path=str(cfg_file),
            )

        # original file gone from upload
        assert not (upload_dir / "hello.txt").exists()

        # exactly one file in done, with correct naming pattern
        done_files = list(done_dir.iterdir())
        assert len(done_files) == 1
        done_name = done_files[0].name
        assert done_name.startswith("hello_")
        assert done_name.endswith(".txt")

        # upload was called with the renamed path
        mock_upload.assert_called_once()
        _, called_path = mock_upload.call_args[0]
        assert called_path.name == done_name

    def test_upload_failure_restores_original(self, workspace):
        tmp_path, upload_dir, done_dir, cfg_file = workspace

        with patch.object(usp, "upload_file_to_sharepoint", side_effect=RuntimeError("network error")):
            with pytest.raises(RuntimeError, match="network error"):
                usp.run(
                    input_dir=str(upload_dir),
                    done_dir=str(done_dir),
                    filename="hello.txt",
                    config_path=str(cfg_file),
                )

        # original filename restored in upload dir
        assert (upload_dir / "hello.txt").exists()
        # done dir still empty
        assert list(done_dir.iterdir()) == []

    def test_missing_input_file_raises(self, workspace):
        tmp_path, upload_dir, done_dir, cfg_file = workspace

        with pytest.raises(FileNotFoundError):
            usp.run(
                input_dir=str(upload_dir),
                done_dir=str(done_dir),
                filename="missing.txt",
                config_path=str(cfg_file),
            )


# ---------------------------------------------------------------------------
# Integration test  (marked so it can be skipped in CI)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestIntegration:
    """
    End-to-end test that uploads hello.txt to real SharePoint, then cleans up.

    Prerequisites:
      - config.json filled with real credentials
      - upload/hello.txt present
      - done/ directory present (or will be created)
      - MSAL device-code auth will be triggered on first run
        (token cached in .token_cache.bin afterwards)

    The test restores the situation afterwards:
      - Re-creates upload/hello.txt
      - Clears done/
    """

    SCRIPT_DIR = Path(__file__).parent
    CONFIG = SCRIPT_DIR / "config.json"
    UPLOAD_DIR = SCRIPT_DIR / "upload"
    DONE_DIR = SCRIPT_DIR / "done"
    ORIGINAL_FILE = "hello.txt"
    ORIGINAL_CONTENT = "hello world\n"

    def setup_method(self):
        """Ensure upload/hello.txt exists before each test."""
        self.UPLOAD_DIR.mkdir(exist_ok=True)
        self.DONE_DIR.mkdir(exist_ok=True)
        write_text(self.UPLOAD_DIR / self.ORIGINAL_FILE, self.ORIGINAL_CONTENT)

    def teardown_method(self):
        """Restore situation: re-create hello.txt, clear done/."""
        # Ensure upload file exists (may have been moved)
        if not (self.UPLOAD_DIR / self.ORIGINAL_FILE).exists():
            write_text(self.UPLOAD_DIR / self.ORIGINAL_FILE, self.ORIGINAL_CONTENT)

        # Clear done/
        for f in self.DONE_DIR.iterdir():
            f.unlink()
        print(f"\nRestored: upload/{self.ORIGINAL_FILE} present, done/ cleared.")

    def test_upload_hello_txt(self):
        """Upload hello.txt to SharePoint, verify done/ contains the renamed file."""
        usp.run(
            input_dir=str(self.UPLOAD_DIR),
            done_dir=str(self.DONE_DIR),
            filename=self.ORIGINAL_FILE,
            config_path=str(self.CONFIG),
        )

        # upload/ should no longer contain hello.txt
        assert not (self.UPLOAD_DIR / self.ORIGINAL_FILE).exists()

        # done/ should contain exactly one file starting with hello_
        done_files = list(self.DONE_DIR.iterdir())
        assert len(done_files) == 1
        assert done_files[0].name.startswith("hello_")
        assert done_files[0].suffix == ".txt"

        print(f"Integration test passed. File in done/: {done_files[0].name}")
