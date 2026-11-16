"""Same input, same bytes, when SOURCE_DATE_EPOCH fixes the moment of rendering."""
import datetime
import io
import time
import zipfile

import docx

from dynamic_pdf import DocumentBuilder
from conftest import fixture_text

EPOCH = 1700000000


def _render(name):
    b = DocumentBuilder.from_markdown(fixture_text(name)).design("auto")
    return b.render(), b.render_docx()


def test_pdf_and_docx_bytes_repeat_under_source_date_epoch(monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", str(EPOCH))
    for name in ("executive.md", "arabic_report.md"):
        first = _render(name)
        time.sleep(1.1)                      # zip and PDF stamps have one-second resolution
        assert _render(name) == first, name


def test_docx_dates_come_from_the_render_not_the_template(monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", str(EPOCH))
    data = DocumentBuilder().meta(title="T").paragraph("x").render_docx()
    want = datetime.datetime.fromtimestamp(EPOCH, datetime.timezone.utc)
    cp = docx.Document(io.BytesIO(data)).core_properties
    assert cp.created.replace(tzinfo=datetime.timezone.utc) == want     # stored in UTC
    assert cp.modified.replace(tzinfo=datetime.timezone.utc) == want
    assert {i.date_time for i in zipfile.ZipFile(io.BytesIO(data)).infolist()} == {want.timetuple()[:6]}


def test_docx_without_source_date_epoch_is_dated_now(monkeypatch):
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    data = DocumentBuilder().meta(title="T").paragraph("x").render_docx()
    created = docx.Document(io.BytesIO(data)).core_properties.created.replace(tzinfo=datetime.timezone.utc)
    now = datetime.datetime.now(datetime.timezone.utc)
    assert abs((now - created).total_seconds()) < 120          # python-docx's template says 2013
