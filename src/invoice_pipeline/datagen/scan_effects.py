"""Rasterize a generated invoice PDF into a degraded "bad scan" image.

Uses PyMuPDF (no system poppler dependency) to render the page, then applies
slight rotation (skew), gaussian noise, mild blur, and JPEG recompression to
mimic a low-quality office scanner/phone photo.
"""

from __future__ import annotations

import io
import random

import numpy as np
import pymupdf
from PIL import Image, ImageFilter


def rasterize_pdf_page(pdf_path: str, page_num: int = 0, dpi: int = 200) -> Image.Image:
    doc = pymupdf.open(pdf_path)
    page = doc[page_num]
    zoom = dpi / 72
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    doc.close()
    return img


def apply_scan_noise(
    img: Image.Image,
    rng: random.Random,
    rotation_range: tuple[float, float] = (-3.5, 3.5),
    noise_sigma: float = 14.0,
    jpeg_quality: int = 45,
) -> Image.Image:
    # Slight skew, filled with white so it reads as a page on a scanner bed.
    angle = rng.uniform(*rotation_range)
    img = img.rotate(angle, expand=True, fillcolor=(255, 255, 255), resample=Image.BICUBIC)

    # Mild blur to simulate an out-of-focus phone photo / low scanner DPI.
    img = img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.4, 1.1)))

    # Gaussian sensor noise.
    arr = np.asarray(img).astype(np.float32)
    noise = np.random.default_rng(rng.randint(0, 2**31 - 1)).normal(0, noise_sigma, arr.shape)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)

    # Slight brightness/contrast unevenness.
    brightness_shift = rng.uniform(-12, 8)
    arr = np.asarray(img).astype(np.float32) + brightness_shift
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    # Recompress through JPEG to introduce blocking artifacts.
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=jpeg_quality)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def make_scanned_image(pdf_path: str, out_path: str, seed: int) -> None:
    rng = random.Random(seed)
    img = rasterize_pdf_page(pdf_path, dpi=200)
    img = apply_scan_noise(img, rng)
    img.save(out_path, format="JPEG", quality=60)
