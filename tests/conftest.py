from pathlib import Path
import numpy as np
import pytest
from PIL import Image


@pytest.fixture
def gradient_jpg(tmp_path: Path) -> Path:
    h, w = 480, 640
    x = np.linspace(0, 255, w, dtype=np.uint8)
    image = np.zeros((h, w, 3), dtype=np.uint8)
    image[..., 0] = x
    image[..., 1] = np.flip(x)
    image[..., 2] = 120
    path = tmp_path / "gradient.jpg"
    Image.fromarray(image, "RGB").save(path, quality=95)
    return path


@pytest.fixture
def transparent_png(tmp_path: Path) -> Path:
    image = np.zeros((200, 200, 4), dtype=np.uint8)
    image[:, :100, :3] = [255, 0, 0]
    image[:, :100, 3] = 0
    image[:, 100:, :3] = [20, 80, 220]
    image[:, 100:, 3] = 255
    path = tmp_path / "transparent.png"
    Image.fromarray(image, "RGBA").save(path)
    return path


@pytest.fixture
def sample_webp(tmp_path: Path) -> Path:
    image = Image.new("RGB", (320, 240), (90, 150, 200))
    path = tmp_path / "sample.webp"
    image.save(path, format="WEBP", lossless=True)
    return path

@pytest.fixture
def exif_rotated_jpg(tmp_path: Path) -> Path:
    image = Image.new("RGB", (240, 140), (240, 240, 240))
    exif = Image.Exif()
    exif[274] = 6
    path = tmp_path / "exif_rotated.jpg"
    image.save(path, quality=95, exif=exif)
    return path


@pytest.fixture
def srgb_icc_png(tmp_path: Path) -> Path:
    from PIL import ImageCms

    image = Image.new("RGB", (220, 180), (110, 160, 200))
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    path = tmp_path / "srgb_icc.png"
    image.save(path, icc_profile=profile)
    return path


@pytest.fixture
def invalid_icc_png(tmp_path: Path) -> Path:
    image = Image.new("RGB", (220, 180), (110, 160, 200))
    path = tmp_path / "invalid_icc.png"
    image.save(path, icc_profile=b"invalid-icc-profile")
    return path


@pytest.fixture
def partial_alpha_png(tmp_path: Path) -> Path:
    image = np.zeros((200, 240, 4), dtype=np.uint8)
    image[:, :80, :3] = [255, 0, 0]
    image[:, :80, 3] = 0
    image[:, 80:160, :3] = [40, 180, 80]
    image[:, 80:160, 3] = 128
    image[:, 160:, :3] = [20, 80, 220]
    image[:, 160:, 3] = 255
    path = tmp_path / "partial_alpha.png"
    Image.fromarray(image, "RGBA").save(path)
    return path
