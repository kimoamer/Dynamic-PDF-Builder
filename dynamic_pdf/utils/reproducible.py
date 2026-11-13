"""The moment a document is stamped with, and byte-for-byte reproducible output.

PDF and DOCX carry a creation time. By default it is the time of rendering. When the
``SOURCE_DATE_EPOCH`` environment variable is set (the reproducible-builds convention, which
ReportLab already honours for PDF), both formats use that instant instead, so the same input
renders to the same bytes.
"""
from __future__ import annotations

import datetime
import io
import os
import zipfile

_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)        # the earliest time a zip entry can hold


def render_time() -> datetime.datetime:
    """``SOURCE_DATE_EPOCH`` when set, otherwise now; always in UTC, without microseconds."""
    raw = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    if raw:
        try:
            return datetime.datetime.fromtimestamp(int(raw), datetime.timezone.utc)
        except (ValueError, OverflowError, OSError):
            pass
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def stamp_zip(data: bytes, when: datetime.datetime) -> bytes:
    """``data`` (a zip package such as a DOCX) with every entry dated ``when``.

    Entry order, names, contents and compression are kept; only the entry timestamps change,
    which are otherwise the wall-clock time of saving and differ on every render."""
    stamp = max(_ZIP_EPOCH, when.timetuple()[:6])
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            new = zipfile.ZipInfo(info.filename, date_time=stamp)
            new.compress_type = info.compress_type
            new.external_attr = info.external_attr
            new.create_system = info.create_system
            dst.writestr(new, src.read(info.filename))
    return out.getvalue()
