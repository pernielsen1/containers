import json
import os
import sys
import zipfile

import pandas as pd
import pytest

ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "archive")
sys.path.insert(0, ARCHIVE_DIR)
from extract import Extract  # noqa: E402


@pytest.fixture
def project(tmp_path):
    """Builds a fake project layout: <root>/archive, <root>/archive_data,
    <root>/output, with archive/archive.json pointing at them via relative
    paths (mirrors the real repo)."""
    root = tmp_path
    archive_index_dir = root / "archive"
    archive_data_dir = root / "archive_data"
    output_dir = root / "output" / "extracted"
    for d in (archive_index_dir, archive_data_dir):
        d.mkdir(parents=True, exist_ok=True)

    config_path = archive_index_dir / "archive.json"
    config_path.write_text(json.dumps({
        "archive_index": "archive",
        "archive_data": "archive_data",
    }), encoding="utf-8")

    return {
        "config_path": str(config_path),
        "archive_index_dir": archive_index_dir,
        "archive_data_dir": archive_data_dir,
        "output_dir": output_dir,
    }


def write_master_index(archive_index_dir, rows):
    pd.DataFrame(rows, columns=Extract.INDEX_COLUMNS).to_csv(
        archive_index_dir / Extract.MASTER_INDEX_FILENAME,
        sep=";", encoding="utf-8-sig", index=False,
    )


def write_zip(archive_data_dir, zip_filename, files):
    """files: dict of {arcname: content}"""
    with zipfile.ZipFile(archive_data_dir / zip_filename, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, content in files.items():
            zf.writestr(arcname, content)


def test_extracts_single_match(project):
    name = "companyinfo_111_20260705_100000.txt"
    write_zip(project["archive_data_dir"], "archive_a.zip", {name: "hello"})
    write_master_index(project["archive_index_dir"], [{
        "type": "companyinfo", "key": "111", "timestamp": "20260705_100000",
        "file_name": name, "zip_archive_filename": "archive_a.zip",
    }])

    extracted = Extract(key="111", output_dir=str(project["output_dir"]), config=project["config_path"]).run()

    assert extracted == 1
    dest = project["output_dir"] / name
    assert dest.exists()
    assert dest.read_text(encoding="utf-8") == "hello"


def test_extracts_all_matches_for_key_across_multiple_zips(project):
    name1 = "companyinfo_222_20260705_100000.txt"
    name2 = "companyinfo_222_20260706_110000.txt"
    write_zip(project["archive_data_dir"], "archive_a.zip", {name1: "first"})
    write_zip(project["archive_data_dir"], "archive_b.zip", {name2: "second"})
    write_master_index(project["archive_index_dir"], [
        {"type": "companyinfo", "key": "222", "timestamp": "20260705_100000",
         "file_name": name1, "zip_archive_filename": "archive_a.zip"},
        {"type": "companyinfo", "key": "222", "timestamp": "20260706_110000",
         "file_name": name2, "zip_archive_filename": "archive_b.zip"},
    ])

    extracted = Extract(key="222", output_dir=str(project["output_dir"]), config=project["config_path"]).run()

    assert extracted == 2
    assert (project["output_dir"] / name1).read_text(encoding="utf-8") == "first"
    assert (project["output_dir"] / name2).read_text(encoding="utf-8") == "second"


def test_no_matches_returns_zero_and_creates_no_files(project):
    write_master_index(project["archive_index_dir"], [{
        "type": "companyinfo", "key": "999", "timestamp": "20260705_100000",
        "file_name": "companyinfo_999_20260705_100000.txt", "zip_archive_filename": "archive_a.zip",
    }])

    extracted = Extract(key="333", output_dir=str(project["output_dir"]), config=project["config_path"]).run()

    assert extracted == 0
    assert not project["output_dir"].exists() or not any(project["output_dir"].iterdir())


def test_missing_master_index_returns_zero(project):
    extracted = Extract(key="111", output_dir=str(project["output_dir"]), config=project["config_path"]).run()
    assert extracted == 0


def test_output_dir_falls_back_to_config_value(project):
    name = "companyinfo_444_20260705_100000.txt"
    write_zip(project["archive_data_dir"], "archive_a.zip", {name: "data"})
    write_master_index(project["archive_index_dir"], [{
        "type": "companyinfo", "key": "444", "timestamp": "20260705_100000",
        "file_name": name, "zip_archive_filename": "archive_a.zip",
    }])

    config = {
        "archive_index": str(project["archive_index_dir"]),
        "archive_data": str(project["archive_data_dir"]),
        "output_dir": str(project["output_dir"]),
    }
    extracted = Extract(key="444", config=config).run()

    assert extracted == 1
    assert (project["output_dir"] / name).exists()


def test_missing_output_dir_raises():
    config = {"archive_index": "archive", "archive_data": "archive_data"}
    with pytest.raises(ValueError):
        Extract(key="111", config=config)


def test_missing_required_config_keys_raises():
    config = {"archive_index": "archive"}
    with pytest.raises(ValueError):
        Extract(key="111", output_dir="out", config=config)


def test_overwrites_existing_file_in_output_dir(project):
    name = "companyinfo_555_20260705_100000.txt"
    write_zip(project["archive_data_dir"], "archive_a.zip", {name: "new-content"})
    write_master_index(project["archive_index_dir"], [{
        "type": "companyinfo", "key": "555", "timestamp": "20260705_100000",
        "file_name": name, "zip_archive_filename": "archive_a.zip",
    }])
    project["output_dir"].mkdir(parents=True, exist_ok=True)
    (project["output_dir"] / name).write_text("old-content", encoding="utf-8")

    Extract(key="555", output_dir=str(project["output_dir"]), config=project["config_path"]).run()

    assert (project["output_dir"] / name).read_text(encoding="utf-8") == "new-content"
