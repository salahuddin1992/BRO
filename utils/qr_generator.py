"""
Helen WiFi - QR Code Generator
Generates QR codes for easy server connection.
"""
import os
import io
import base64
import logging

import qrcode

logger = logging.getLogger("BRO.qr")


def generate_qr_code(url, output_path=None):
    """Generate QR code for a URL. Returns base64 PNG if no output_path."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    if output_path:
        img.save(output_path)
        logger.info(f"QR code saved: {output_path}")
        return output_path

    # Return base64-encoded PNG
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    b64 = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{b64}"
