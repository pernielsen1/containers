import json
import os
import sys
import zipfile

import pandas as pd
import pytest

ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "archive")
sys.path.insert(0, ARCHIVE_DIR)
import archiver  # noqa: E402


@pytest.mark.parametrize(
    "name,expected",
    [
        ("companyinfo_350575093_20260705_181909.txt", ("companyinfo", "350575093", "20260705_181909")),
        ("type_key_20260705181909.txt", ("type", "key", "20260705181909")),
        ("companyinfo_350575093_20260705_181909_extra.txt",
         ("companyinfo", "350575093", "20260705_181909_extra")),
    ],
)
def test_parse_filename_well_formed(name, expected):
    assert archiver.parse_filename(name) == expected


@pytest.mark.parametrize("name", ["nounderscore.txt", "only_one.txt"])
def test_parse_filename_malformed(name):
    assert archiver.parse_filename(name) is None


@pytest.fixture
def project(tmp_path):
    """Builds a fake project layout mirroring the real repo:
    <root>/output, <root>/output/done, <root>/archive, <root>/archive_data
    with archive/archive.json pointing at them via relative paths."""
    root = tmp_path
    input_dir = root / "output"
    done_dir = input_dir / "done"
    archive_index_dir = root / "archive"
    archive_data_dir = root / "archive_data"
    for d in (input_dir, done_dir, archive_index_dir, archive_data_dir):
        d.mkdir(parents=True, exist_ok=True)

    config_path = archive_index_dir / "archive.json"
    config_path.write_text(json.dumps({
        "input_dir": "output",
        "done_dir": "output/done",
        "archive_index": "archive",
        "archive_data": "archive_data",
    }), encoding="utf-8")

    return {
        "config_path": str(config_path),
        "input_dir": input_dir,
        "done_dir": done_dir,
        "archive_index_dir": archive_index_dir,
        "archive_data_dir": archive_data_dir,
    }


def write_input_file(input_dir, name, content="data"):
    (input_dir / name).write_text(content, encoding="utf-8")


def read_master_index(archive_index_dir):
    path = archive_index_dir / archiver.MASTER_INDEX_FILENAME
    return pd.read_csv(path, sep=";", encoding="utf-8-sig", dtype=str)


def test_main_zips_indexes_and_moves_files(project):
    write_input_file(project["input_dir"], "companyinfo_111_20260705_100000.txt")
    write_input_file(project["input_dir"], "companyinfo_222_20260705_100001.txt")

    archiver.main(project["config_path"])

    assert not any(project["input_dir"].glob("*.txt"))
    assert len(list(project["done_dir"].glob("*.txt"))) == 2

    zips = list(project["archive_data_dir"].glob("*.zip"))
    assert len(zips) == 1
    with zipfile.ZipFile(zips[0]) as zf:
        assert sorted(zf.namelist()) == [
            "companyinfo_111_20260705_100000.txt",
            "companyinfo_222_20260705_100001.txt",
        ]

    index_df = read_master_index(project["archive_index_dir"])
    assert len(index_df) == 2
    assert set(index_df["key"]) == {"111", "222"}
    assert not (project["archive_index_dir"] / archiver.TEMP_INDEX_FILENAME).exists()


def test_main_with_no_input_files_is_a_noop(project):
    archiver.main(project["config_path"])
    assert not (project["archive_index_dir"] / archiver.MASTER_INDEX_FILENAME).exists()
    assert not list(project["archive_data_dir"].glob("*.zip"))


def test_malformed_filenames_are_skipped_and_left_in_place(project):
    write_input_file(project["input_dir"], "nounderscore.txt")
    write_input_file(project["input_dir"], "companyinfo_333_20260705_100002.txt")

    archiver.main(project["config_path"])

    assert (project["input_dir"] / "nounderscore.txt").exists()
    assert not (project["input_dir"] / "companyinfo_333_20260705_100002.txt").exists()

    index_df = read_master_index(project["archive_index_dir"])
    assert list(index_df["key"]) == ["333"]


def test_restart_after_crash_before_move_does_not_duplicate_index_rows(project):
    """Simulates a crash after the master index was updated but before the
    file was moved to done_dir: the file is still sitting in input_dir and
    the master index already has a row for it. Re-running must not add a
    second row, even though the file gets re-zipped."""
    name = "companyinfo_444_20260705_100003.txt"
    write_input_file(project["input_dir"], name)

    existing_row = pd.DataFrame([{
        "type": "companyinfo",
        "key": "444",
        "timestamp": "20260705_100003",
        "file_name": name,
        "zip_archive_filename": "archive_prior_run.zip",
    }])
    existing_row.to_csv(
        project["archive_index_dir"] / archiver.MASTER_INDEX_FILENAME,
        sep=";", encoding="utf-8-sig", index=False,
    )

    archiver.main(project["config_path"])

    index_df = read_master_index(project["archive_index_dir"])
    assert len(index_df) == 1
    assert index_df.iloc[0]["zip_archive_filename"] == "archive_prior_run.zip"
    # file still gets moved to done despite the index already knowing about it
    assert (project["done_dir"] / name).exists()
