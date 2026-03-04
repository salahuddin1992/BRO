"""
Helen WiFi - File Compression Utilities
Uses zstandard for fast file compression/decompression.
"""
import os
import logging
import warnings

# zstandard may emit deprecation warnings about its legacy C-backend module
# name.  Suppress them since functionality is unaffected.
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    import zstandard as zstd

logger = logging.getLogger("BRO.compression")

# Compression level: 3 is a good balance of speed and ratio
COMPRESSION_LEVEL = 3

# Only compress files larger than 1KB
MIN_COMPRESS_SIZE = 1024

# File types that benefit from compression (text, documents, code)
COMPRESSIBLE_EXTS = {
    "txt", "csv", "json", "xml", "html", "css", "js", "py",
    "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods",
    "log", "md", "yaml", "yml", "ini", "cfg", "conf",
}


def should_compress(filename, file_size):
    """Check if a file should be compressed."""
    if file_size < MIN_COMPRESS_SIZE:
        return False
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in COMPRESSIBLE_EXTS


def compress_file(input_path, output_path=None):
    """Compress a file using zstandard. Returns output path."""
    if output_path is None:
        output_path = input_path + ".zst"

    cctx = zstd.ZstdCompressor(level=COMPRESSION_LEVEL)
    with open(input_path, "rb") as ifh, open(output_path, "wb") as ofh:
        cctx.copy_stream(ifh, ofh)

    original_size = os.path.getsize(input_path)
    compressed_size = os.path.getsize(output_path)
    ratio = (1 - compressed_size / original_size) * 100 if original_size > 0 else 0
    logger.info(f"Compressed {input_path}: {original_size} -> {compressed_size} ({ratio:.1f}% reduction)")
    return output_path


def decompress_file(input_path, output_path=None):
    """Decompress a zstandard file. Returns output path."""
    if output_path is None:
        output_path = input_path.removesuffix(".zst")

    dctx = zstd.ZstdDecompressor()
    with open(input_path, "rb") as ifh, open(output_path, "wb") as ofh:
        dctx.copy_stream(ifh, ofh)

    return output_path


def compress_data(data):
    """Compress bytes data. Returns compressed bytes."""
    cctx = zstd.ZstdCompressor(level=COMPRESSION_LEVEL)
    return cctx.compress(data)


def decompress_data(data):
    """Decompress bytes data. Returns decompressed bytes."""
    dctx = zstd.ZstdDecompressor()
    return dctx.decompress(data)
