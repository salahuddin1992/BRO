"""
Helen WiFi - Image Thumbnail Generator
Uses Pillow to create thumbnails for uploaded images.
"""
import os
import logging

from PIL import Image

logger = logging.getLogger("BRO.thumbnails")

THUMB_SIZE = (200, 200)
THUMB_DIR_NAME = "thumbnails"
IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "bmp", "webp"}


def ensure_thumb_dir(upload_folder):
    """Create thumbnails directory inside upload folder."""
    thumb_dir = os.path.join(upload_folder, THUMB_DIR_NAME)
    os.makedirs(thumb_dir, exist_ok=True)
    return thumb_dir


def generate_thumbnail(upload_folder, saved_as):
    """Generate a thumbnail for an image file. Returns thumbnail filename or None."""
    ext = saved_as.rsplit(".", 1)[-1].lower() if "." in saved_as else ""
    if ext not in IMAGE_EXTS:
        return None

    source = os.path.join(upload_folder, saved_as)
    if not os.path.isfile(source):
        return None

    thumb_dir = ensure_thumb_dir(upload_folder)
    thumb_name = f"thumb_{saved_as}"
    thumb_path = os.path.join(thumb_dir, thumb_name)

    try:
        with Image.open(source) as img:
            img.thumbnail(THUMB_SIZE, Image.LANCZOS)
            # Convert RGBA to RGB for JPEG compatibility
            if img.mode in ("RGBA", "P") and ext in ("jpg", "jpeg"):
                img = img.convert("RGB")
            img.save(thumb_path, quality=80)
        logger.info(f"Thumbnail created: {thumb_name}")
        return thumb_name
    except Exception as e:
        logger.warning(f"Thumbnail generation failed for {saved_as}: {e}")
        return None


def get_thumbnail_path(upload_folder, saved_as):
    """Get path to thumbnail if it exists."""
    thumb_dir = os.path.join(upload_folder, THUMB_DIR_NAME)
    thumb_name = f"thumb_{saved_as}"
    thumb_path = os.path.join(thumb_dir, thumb_name)
    if os.path.isfile(thumb_path):
        return thumb_path
    return None
