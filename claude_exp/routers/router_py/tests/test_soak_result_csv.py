"""soak_result_csv.record_result() is the single writer soak_resilience_hard.py, run_soak.sh (via
a bash->python bridge - see run_soak.sh's own record_result()), and soak_resilience_light.py all
funnel through - see [[project_resilience_hard_soak]] and this session's consolidation of what
used to be a hand-synced bash copy. It had no test coverage before the `comment` column (and its
sanitization) was added - these tests pin the format directly rather than relying on manual CSV
inspection after a soak run.
"""
import soak_result_csv as src


def _point_at_tmp_files(monkeypatch, tmp_path):
    results_csv = tmp_path / "soak_results.csv"
    summary_csv = tmp_path / "soak_summary.csv"
    monkeypatch.setattr(src, "CSV_RESULTS_DIR", str(tmp_path))
    monkeypatch.setattr(src, "SOAK_RESULTS_CSV", str(results_csv))
    monkeypatch.setattr(src, "SOAK_SUMMARY_CSV", str(summary_csv))
    return results_csv, summary_csv


def test_record_result_writes_header_once_with_comment_column(monkeypatch, tmp_path):
    results_csv, summary_csv = _point_at_tmp_files(monkeypatch, tmp_path)

    src.record_result("router_py;100;10;491;491;0;49.06;2.98;3.33;3.51;4.59;5.6")
    src.record_result("router_py;100;10;491;491;0;49.06;2.98;3.33;3.51;4.59;5.6")

    results_lines = results_csv.read_text(encoding="utf-8-sig").splitlines()
    summary_lines = summary_csv.read_text(encoding="utf-8-sig").splitlines()
    assert results_lines[0].endswith(";comment")
    assert summary_lines[0].endswith(";comment")
    # header written once, not re-written/duplicated on a second call
    assert len(results_lines) == 3
    assert len(summary_lines) == 3


def test_record_result_converts_dot_to_comma_decimal(monkeypatch, tmp_path):
    results_csv, summary_csv = _point_at_tmp_files(monkeypatch, tmp_path)

    src.record_result("router_py;100;10;491;491;0;49.06;2.98;3.33;3.51;4.59;5.6")

    row = results_csv.read_text(encoding="utf-8-sig").splitlines()[1]
    assert ";49,06;2,98;3,33;3,51;4,59;5,6;" in row
    summary_row = summary_csv.read_text(encoding="utf-8-sig").splitlines()[1]
    assert summary_row.endswith(";100;10;2,98;3,33;4,59;")  # p50/p90/p99 only + empty comment


def test_record_result_sanitizes_comment_delimiters_and_newlines(monkeypatch, tmp_path):
    """A human-supplied comment must never be able to inject a field or split a row - see
    record_result()'s own docstring on why comment is sanitized before being written."""
    results_csv, summary_csv = _point_at_tmp_files(monkeypatch, tmp_path)

    src.record_result(
        "router_py;100;10;491;491;0;49.06;2.98;3.33;3.51;4.59;5.6",
        comment="semi;colon\nand newline  ",
    )

    results_row = results_csv.read_text(encoding="utf-8-sig").splitlines()[1]
    summary_row = summary_csv.read_text(encoding="utf-8-sig").splitlines()[1]
    assert results_row.endswith(";semi,colon and newline")
    assert summary_row.endswith(";semi,colon and newline")
    # exactly one row of data landed in each file - a stray newline in the comment must not have
    # split it into two
    assert len(results_csv.read_text(encoding="utf-8-sig").splitlines()) == 2
    assert len(summary_csv.read_text(encoding="utf-8-sig").splitlines()) == 2


def test_record_result_advice_columns_are_optional(monkeypatch, tmp_path):
    """soak_resilience_hard.py appends four extra advice_* fields; every other producer's rows
    stay 12 fields - see module docstring's 'old rows stay short, not padded' convention. Both
    shapes must land correctly in soak_results.csv, and soak_summary.csv only ever reads the
    first 12 regardless."""
    results_csv, summary_csv = _point_at_tmp_files(monkeypatch, tmp_path)

    src.record_result(
        "router_py_real_crypto_during_kill;100;42;4051;0;4051;96.44;0;0;0;0;0;331;331;332;332",
        comment="baseline 20260904",
    )

    results_row = results_csv.read_text(encoding="utf-8-sig").splitlines()[1]
    summary_row = summary_csv.read_text(encoding="utf-8-sig").splitlines()[1]
    assert results_row.endswith(";331;331;332;332;baseline 20260904")
    assert summary_row.endswith(";100;42;0;0;0;baseline 20260904")
