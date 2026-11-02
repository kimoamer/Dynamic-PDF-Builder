"""P0-02: encryption fails closed."""
import builtins
import pytest
from dynamic_pdf import DocumentBuilder, EncryptionError, render_from_json


def _block_pikepdf(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "pikepdf" or name.startswith("pikepdf."):
            raise ImportError("No module named 'pikepdf'")
        return real_import(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", fake_import)


def test_missing_backend_raises_and_writes_nothing(tmp_path, monkeypatch):
    _block_pikepdf(monkeypatch)
    out = tmp_path / "secret.pdf"
    b = DocumentBuilder().paragraph("confidential").encrypt("owner", "user")
    with pytest.raises(EncryptionError):
        b.render(str(out))
    assert not out.exists()
    with pytest.raises(EncryptionError):
        b.render()


def test_missing_backend_json_path(monkeypatch):
    _block_pikepdf(monkeypatch)
    payload = {"meta": {"encrypt": True, "owner_password": "o"},
               "blocks": [{"type": "paragraph", "text": "x"}]}
    with pytest.raises(EncryptionError):
        render_from_json(payload)


def test_encrypt_without_password_is_refused(tmp_path):
    b = DocumentBuilder().paragraph("x")
    b._meta.encrypt = True
    with pytest.raises(EncryptionError):
        b.render(str(tmp_path / "x.pdf"))
    assert not (tmp_path / "x.pdf").exists()


def test_encryption_positive(tmp_path):
    pikepdf = pytest.importorskip("pikepdf")
    out = tmp_path / "enc.pdf"
    DocumentBuilder().paragraph("confidential").encrypt("owner-pw", "user-pw").render(str(out))
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(out)
    with pikepdf.open(out, password="user-pw") as pdf:
        assert pdf.is_encrypted
        assert len(pdf.pages) == 1
