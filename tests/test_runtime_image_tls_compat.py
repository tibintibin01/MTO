"""Offline compatibility checks for the two approved runtime security updates."""

from io import BytesIO
import ssl

import certifi
import customtkinter as ctk
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from ui.dossier import _load_dossier_seal


def test_dossier_seal_and_customtkinter_image_keep_alpha_and_scaling():
    seal = _load_dossier_seal(64)
    assert seal.mode == "RGBA"
    assert seal.size == (64, 64)
    assert seal.getpixel((0, 0))[3] == 0
    assert seal.getpixel((32, 32))[3] == 255
    image = ctk.CTkImage(light_image=seal, dark_image=seal, size=(32, 32))
    assert image.cget("size") == (32, 32)
    assert image.cget("light_image") is seal


def test_png_jpeg_ico_and_reportlab_image_embedding_remain_compatible():
    source = Image.new("RGB", (64, 64), (10, 80, 120))
    for file_format in ("PNG", "JPEG", "ICO"):
        data = BytesIO()
        source.save(data, format=file_format)
        data.seek(0)
        with Image.open(data) as decoded:
            decoded.load()
            assert decoded.size == (64, 64)
            pixel = decoded.convert("RGB").getpixel((32, 32))
            # JPEG is lossy; PNG/ICO must preserve these pixels exactly.
            tolerance = 2 if file_format == "JPEG" else 0
            assert all(abs(a - b) <= tolerance for a, b in zip(pixel, (10, 80, 120)))
    target = BytesIO()
    pdf = Canvas(target, pagesize=(100, 100))
    pdf.drawImage(ImageReader(source), 0, 0, width=64, height=64)
    pdf.showPage()
    pdf.save()
    assert target.getvalue().startswith(b"%PDF-")
    assert b"/Subtype /Image" in target.getvalue()


def test_public_ca_bundle_loads_without_disabling_tls_verification():
    # No network request or office CA/config access. The configured LAN CA is
    # independently covered by the existing client/TLS regression suite.
    context = ssl.create_default_context(cafile=certifi.where())
    assert context.cert_store_stats()["x509_ca"] > 0
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
