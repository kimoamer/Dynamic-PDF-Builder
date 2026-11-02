"""P0-04: bounded, policy-checked asset loading (no surprise network access)."""
import base64
import socket
import pytest
from dynamic_pdf import DocumentBuilder, AssetPolicy, AssetError, ResourceLimitError
from dynamic_pdf.assets import load_image, load_asset_bytes
from dynamic_pdf.schema.blocks import ImageBlock


@pytest.fixture
def no_network(monkeypatch):
    calls = []

    def boom(*a, **kw):
        calls.append(a)
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    return calls


def test_local_image_renders(png_path):
    DocumentBuilder().add_block(ImageBlock(src=png_path, caption="Cap")).render()


def test_remote_refused_by_default_without_network(no_network):
    with pytest.raises(AssetError, match="network access disabled"):
        load_image("https://example.com/logo.png")
    with pytest.raises(Exception):
        DocumentBuilder().image("https://example.com/logo.png").render()
    assert no_network == []


def test_remote_logo_in_theme_refused(no_network):
    from dynamic_pdf.themes.registry import get_theme, register_theme
    t = get_theme("claude")
    t.name = "test_remote_logo"
    t.header_footer.enabled = True
    t.header_footer.header_style = "logo_left"
    t.header_footer.logo = "http://169.254.169.254/latest/meta-data"
    register_theme(t)
    with pytest.raises(AssetError):
        DocumentBuilder(theme=t.name).paragraph("x").render()
    b = DocumentBuilder(theme=t.name).quality("permissive").paragraph("x")
    b.render()
    assert any(d["code"] == "asset_failed" for d in b.diagnostics)
    assert no_network == []


def test_private_network_and_schemes_blocked(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 0))])
    pol = AssetPolicy(allow_remote=True)
    with pytest.raises(AssetError, match="non-public"):
        load_asset_bytes("http://internal.example/x.png", pol)
    for src in ("file:///etc/passwd", "ftp://x/y.png"):
        with pytest.raises(AssetError):
            load_asset_bytes(src, pol)


def test_host_allowlist():
    pol = AssetPolicy(allow_remote=True, allowed_hosts=("cdn.example.com",))
    with pytest.raises(AssetError, match="allowlist"):
        load_asset_bytes("https://evil.example.net/x.png", pol)


def test_base_dir_confinement(tmp_path, png_path):
    root = tmp_path / "assets"
    root.mkdir()
    pol = AssetPolicy(base_dir=str(root))
    with pytest.raises(AssetError, match="outside"):
        load_asset_bytes(png_path, pol)
    with pytest.raises(AssetError, match="outside"):
        load_asset_bytes("../img.png", pol)


def test_size_and_pixel_limits(png_path, tmp_path):
    with pytest.raises(ResourceLimitError):
        load_asset_bytes(png_path, AssetPolicy(max_bytes=10))
    from PIL import Image
    big = tmp_path / "big.png"
    Image.new("L", (3000, 3000)).save(big)
    with pytest.raises(ResourceLimitError):
        load_image(str(big), AssetPolicy(max_pixels=1_000_000))


def test_data_uri(png_path):
    data = base64.b64encode(open(png_path, "rb").read()).decode()
    buf, size = load_image(f"data:image/png;base64,{data}")
    assert size == (40, 20)
    with pytest.raises(AssetError):
        load_image("data:text/html;base64,PGgxPg==")


def test_not_an_image(tmp_path):
    p = tmp_path / "fake.png"
    p.write_text("<svg onload=alert(1)>")
    with pytest.raises(AssetError, match="Not a valid image"):
        load_image(str(p))


def test_fonts_never_downloaded_during_render(no_network):
    import dynamic_pdf.fonts.manager as fm
    fm._registered = False
    DocumentBuilder().paragraph("x").render()
    assert no_network == []
