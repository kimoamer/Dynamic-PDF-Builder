"""
Asset resolver — the single, bounded entry point for loading images/logos.

Defaults are safe for untrusted documents:
  * local files allowed (optionally confined to ``base_dir``),
  * ``data:image/...;base64`` URIs allowed (size-bounded),
  * **no network access** unless ``allow_remote=True``; remote fetches are
    restricted to http(s), optional host allowlist, public IPs only (unless
    ``allow_private_networks``), re-validated on every redirect, with a
    timeout and byte cap,
  * decoded images are capped by pixel count (decompression-bomb guard).
"""
from __future__ import annotations

import base64
import binascii
import io
import ipaddress
import os
import socket
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional, Tuple

from .utils.errors import AssetError, ResourceLimitError

_IMAGE_TYPES = {
    "image/png", "image/jpeg", "image/jpg", "image/gif",
    "image/bmp", "image/webp", "image/tiff",
}


@dataclass(frozen=True)
class AssetPolicy:
    allow_local: bool = True
    base_dir: Optional[str] = None
    allow_data_uri: bool = True
    allow_remote: bool = False
    allowed_hosts: Tuple[str, ...] = ()
    allow_private_networks: bool = False
    max_bytes: int = 20 * 1024 * 1024
    max_pixels: int = 50_000_000
    timeout_s: float = 10.0
    max_redirects: int = 3


def _is_remote(src: str) -> bool:
    return urllib.parse.urlsplit(src).scheme.lower() in ("http", "https", "ftp", "file")


def _check_host(host: str, policy: AssetPolicy) -> None:
    host = (host or "").lower().rstrip(".")
    if not host:
        raise AssetError("Remote asset URL has no host")
    if policy.allowed_hosts and host not in {h.lower() for h in policy.allowed_hosts}:
        raise AssetError(f"Remote host not in allowlist: {host}")
    if policy.allow_private_networks:
        return
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise AssetError(f"Cannot resolve host {host}: {e}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            raise AssetError(f"Remote host {host} resolves to non-public address {ip}")


def _validate_url(url: str, policy: AssetPolicy) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() not in ("http", "https"):
        raise AssetError(f"URL scheme not allowed: {parts.scheme!r}")
    _check_host(parts.hostname or "", policy)


class _ValidatingRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, policy: AssetPolicy):
        self.policy = policy
        self.count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.count += 1
        if self.count > self.policy.max_redirects:
            raise AssetError("Too many redirects")
        _validate_url(newurl, self.policy)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch_remote(url: str, policy: AssetPolicy) -> bytes:
    if not policy.allow_remote:
        raise AssetError(
            f"Remote asset refused (network access disabled by AssetPolicy): {url}")
    _validate_url(url, policy)
    opener = urllib.request.build_opener(_ValidatingRedirect(policy))
    req = urllib.request.Request(url, headers={"User-Agent": "dynamic-pdf-builder"})
    try:
        with opener.open(req, timeout=policy.timeout_s) as resp:
            ctype = (resp.headers.get_content_type() or "").lower()
            if ctype not in _IMAGE_TYPES:
                raise AssetError(f"Remote asset is not an allowed image type: {ctype}")
            data = resp.read(policy.max_bytes + 1)
    except AssetError:
        raise
    except Exception as e:  # network/HTTP errors → typed
        raise AssetError(f"Failed to fetch {url}: {e}") from e
    if len(data) > policy.max_bytes:
        raise ResourceLimitError(f"Remote asset exceeds {policy.max_bytes} bytes: {url}")
    return data


def _read_data_uri(src: str, policy: AssetPolicy) -> bytes:
    if not policy.allow_data_uri:
        raise AssetError("data: URIs are disabled by AssetPolicy")
    header, _, payload = src.partition(",")
    mime = header[5:].split(";")[0].lower()
    if mime not in _IMAGE_TYPES:
        raise AssetError(f"data: URI type not allowed: {mime or '(none)'}")
    if ";base64" not in header.lower():
        raise AssetError("Only base64 data: URIs are supported")
    if len(payload) > policy.max_bytes * 4 // 3 + 4:
        raise ResourceLimitError(f"data: URI exceeds {policy.max_bytes} bytes")
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as e:
        raise AssetError(f"Invalid base64 in data: URI: {e}") from e


def _read_local(src: str, policy: AssetPolicy) -> bytes:
    if not policy.allow_local:
        raise AssetError(f"Local asset refused by AssetPolicy: {src}")
    path = os.path.realpath(src if not policy.base_dir else os.path.join(policy.base_dir, src))
    if policy.base_dir:
        root = os.path.realpath(policy.base_dir)
        if os.path.commonpath([root, path]) != root:
            raise AssetError(f"Local asset outside allowed base_dir: {src}")
    if not os.path.isfile(path):
        raise AssetError(f"Asset file not found: {src}")
    size = os.path.getsize(path)
    if size > policy.max_bytes:
        raise ResourceLimitError(f"Asset {src} is {size} bytes; limit {policy.max_bytes}")
    with open(path, "rb") as f:
        return f.read()


def load_asset_bytes(src: str, policy: Optional[AssetPolicy] = None) -> bytes:
    """Load raw bytes for ``src`` under ``policy``. Raises AssetError/ResourceLimitError."""
    policy = policy or AssetPolicy()
    if not isinstance(src, str) or not src.strip():
        raise AssetError("Empty asset source")
    src = src.strip()
    if src.lower().startswith("data:"):
        return _read_data_uri(src, policy)
    if _is_remote(src):
        if urllib.parse.urlsplit(src).scheme.lower() in ("file", "ftp"):
            raise AssetError(f"URL scheme not allowed: {src.split(':', 1)[0]}")
        return _fetch_remote(src, policy)
    return _read_local(src, policy)


def load_image(src: str, policy: Optional[AssetPolicy] = None):
    """Return ``(BytesIO, (width_px, height_px))`` for a validated raster image."""
    from PIL import Image as PILImage
    policy = policy or AssetPolicy()
    data = load_asset_bytes(src, policy)
    try:
        with PILImage.open(io.BytesIO(data)) as im:
            w, h = im.size
            if w * h > policy.max_pixels:
                raise ResourceLimitError(
                    f"Image {w}x{h} exceeds pixel limit {policy.max_pixels}: {_short(src)}")
            im.verify()
    except ResourceLimitError:
        raise
    except Exception as e:
        raise AssetError(f"Not a valid image: {_short(src)} ({e})") from e
    return io.BytesIO(data), (w, h)


def _short(src: str) -> str:
    return src if len(src) <= 80 else src[:77] + "..."


__all__ = ["AssetPolicy", "load_asset_bytes", "load_image"]
