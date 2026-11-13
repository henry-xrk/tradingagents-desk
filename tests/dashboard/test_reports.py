"""Report paths cannot leave the results directory."""

from pathlib import Path

import pytest

from backend.errors import DashboardError
from backend.services.reports import resolve_html_report


def test_html_inside_the_results_directory_is_served(tmp_path: Path):
    report = tmp_path / "complete_report.html"
    report.write_text("<html></html>", encoding="utf-8")
    assert resolve_html_report(str(report), tmp_path) == report.resolve()


def test_relative_html_stays_under_the_root(tmp_path: Path):
    folder = tmp_path / "reports"
    folder.mkdir()
    report = folder / "complete_report.html"
    report.write_text("<html></html>", encoding="utf-8")
    assert resolve_html_report("reports/complete_report.html", tmp_path) == report.resolve()


def test_path_escape_is_rejected(tmp_path: Path):
    root = tmp_path / "results"
    root.mkdir()
    outside = tmp_path / "complete_report.html"
    outside.write_text("<html></html>", encoding="utf-8")
    with pytest.raises(DashboardError) as raised:
        resolve_html_report(str(outside), root)
    assert raised.value.status == 403


def test_non_html_is_not_served(tmp_path: Path):
    notes = tmp_path / "notes.txt"
    notes.write_text("hello", encoding="utf-8")
    with pytest.raises(DashboardError) as raised:
        resolve_html_report(str(notes), tmp_path)
    assert raised.value.status == 404
