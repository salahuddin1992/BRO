#!/usr/bin/env python3
"""
Helen WiFi - Icon Generator
Creates professional PNG and ICO icon files for the desktop application.
Uses only Python standard library (struct + zlib) - no Pillow needed.
"""
import struct
import zlib
import os
import math

DIR = os.path.dirname(os.path.abspath(__file__))
ICON_DIR = os.path.join(DIR, "electron", "icons")


def create_png(width, height, pixels):
    """Create a PNG file from raw RGBA pixel data."""

    def chunk(chunk_type, data):
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    # Signature
    sig = b'\x89PNG\r\n\x1a\n'

    # IHDR
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    ihdr_chunk = chunk(b'IHDR', ihdr)

    # IDAT - pixel data with filter bytes
    raw = b''
    for y in range(height):
        raw += b'\x00'  # filter: none
        for x in range(width):
            idx = (y * width + x) * 4
            raw += bytes(pixels[idx:idx + 4])

    compressed = zlib.compress(raw, 9)
    idat_chunk = chunk(b'IDAT', compressed)

    # IEND
    iend_chunk = chunk(b'IEND', b'')

    return sig + ihdr_chunk + idat_chunk + iend_chunk


def lerp(a, b, t):
    """Linear interpolation."""
    return int(a + (b - a) * t)


def draw_icon(size):
    """Draw the Helen WiFi icon at given size. Returns RGBA pixel list."""
    pixels = [0] * (size * size * 4)

    cx, cy = size / 2, size / 2
    radius = size * 0.45
    border = max(1, size // 64)

    # Colors
    bg_top = (10, 10, 30)       # Dark blue-black
    bg_bot = (20, 15, 50)       # Slightly purple
    accent = (0, 212, 255)      # Cyan
    accent2 = (0, 150, 255)     # Blue
    white = (240, 240, 250)

    for y in range(size):
        for x in range(size):
            idx = (y * size + x) * 4
            dx = x - cx
            dy = y - cy
            dist = math.sqrt(dx * dx + dy * dy)

            # Outside circle = transparent
            if dist > radius + 1:
                pixels[idx] = 0
                pixels[idx + 1] = 0
                pixels[idx + 2] = 0
                pixels[idx + 3] = 0
                continue

            # Anti-aliased edge
            if dist > radius - 1:
                alpha = max(0, min(255, int(255 * (radius + 1 - dist) / 2)))
            else:
                alpha = 255

            # Background gradient (top to bottom)
            t = y / size
            r = lerp(bg_top[0], bg_bot[0], t)
            g = lerp(bg_top[1], bg_bot[1], t)
            b = lerp(bg_top[2], bg_bot[2], t)

            # Subtle radial glow from center
            glow_dist = dist / radius
            if glow_dist < 0.7:
                glow = 1 - glow_dist / 0.7
                glow = glow * glow * 0.15
                r = min(255, int(r + accent[0] * glow))
                g = min(255, int(g + accent[1] * glow))
                b = min(255, int(b + accent[2] * glow))

            # Border ring
            if dist > radius - border * 2.5 and dist <= radius:
                ring_t = (dist - (radius - border * 2.5)) / (border * 2.5)
                ring_alpha = math.sin(ring_t * math.pi) * 0.8
                # Gradient border from cyan to blue
                angle = math.atan2(dy, dx)
                bt = (angle + math.pi) / (2 * math.pi)
                br = lerp(accent[0], accent2[0], bt)
                bg_ = lerp(accent[1], accent2[1], bt)
                bb = lerp(accent[2], accent2[2], bt)
                r = int(r * (1 - ring_alpha) + br * ring_alpha)
                g = int(g * (1 - ring_alpha) + bg_ * ring_alpha)
                b = int(b * (1 - ring_alpha) + bb * ring_alpha)

            pixels[idx] = min(255, max(0, r))
            pixels[idx + 1] = min(255, max(0, g))
            pixels[idx + 2] = min(255, max(0, b))
            pixels[idx + 3] = alpha

    # Draw WiFi arcs
    arc_cx = cx
    arc_cy = cy - size * 0.05
    for arc_i in range(3):
        arc_radius = size * (0.12 + arc_i * 0.08)
        arc_width = max(2, size * 0.025)
        arc_brightness = 1.0 - arc_i * 0.2

        for y in range(size):
            for x in range(size):
                dx = x - arc_cx
                dy = y - arc_cy
                dist = math.sqrt(dx * dx + dy * dy)

                # Only draw upper half (WiFi waves go up)
                angle = math.atan2(-dy, dx)
                if angle < math.pi * 0.2 or angle > math.pi * 0.8:
                    continue

                # Arc band
                dist_from_arc = abs(dist - arc_radius)
                if dist_from_arc < arc_width:
                    idx = (y * size + x) * 4
                    if pixels[idx + 3] == 0:
                        continue

                    # Anti-alias
                    arc_alpha = max(0, 1 - dist_from_arc / arc_width)
                    arc_alpha = arc_alpha * arc_brightness * 0.9

                    cr = int(accent[0] * arc_alpha + pixels[idx] * (1 - arc_alpha))
                    cg = int(accent[1] * arc_alpha + pixels[idx + 1] * (1 - arc_alpha))
                    cb = int(accent[2] * arc_alpha + pixels[idx + 2] * (1 - arc_alpha))

                    pixels[idx] = min(255, cr)
                    pixels[idx + 1] = min(255, cg)
                    pixels[idx + 2] = min(255, cb)

    # Draw WiFi dot at center of arcs
    dot_radius = size * 0.035
    for y in range(size):
        for x in range(size):
            dx = x - arc_cx
            dy = y - arc_cy
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < dot_radius + 1:
                idx = (y * size + x) * 4
                if pixels[idx + 3] == 0:
                    continue
                dot_alpha = min(1.0, max(0, (dot_radius + 1 - dist) / 2))
                pixels[idx] = int(accent[0] * dot_alpha + pixels[idx] * (1 - dot_alpha))
                pixels[idx + 1] = int(accent[1] * dot_alpha + pixels[idx + 1] * (1 - dot_alpha))
                pixels[idx + 2] = int(accent[2] * dot_alpha + pixels[idx + 2] * (1 - dot_alpha))

    # Draw "H" letter below WiFi symbol
    h_scale = size / 256
    h_left = int(cx - size * 0.16)
    h_right = int(cx + size * 0.16)
    h_top = int(cy + size * 0.08)
    h_bottom = int(cy + size * 0.35)
    h_mid = (h_top + h_bottom) // 2
    h_stroke = max(2, int(size * 0.04))

    for y in range(max(0, h_top), min(size, h_bottom)):
        for x in range(max(0, h_left), min(size, h_right)):
            draw = False
            # Left vertical
            if abs(x - h_left) < h_stroke:
                draw = True
            # Right vertical
            if abs(x - h_right + h_stroke) < h_stroke:
                draw = True
            # Horizontal bar
            if abs(y - h_mid) < h_stroke // 2 + 1 and x >= h_left and x <= h_right:
                draw = True

            if draw:
                idx = (y * size + x) * 4
                if pixels[idx + 3] == 0:
                    continue
                # Gradient H: white to cyan
                ht = (y - h_top) / max(1, h_bottom - h_top)
                hr = lerp(white[0], accent[0], ht * 0.5)
                hg = lerp(white[1], accent[1], ht * 0.5)
                hb = lerp(white[2], accent[2], ht * 0.5)
                blend = 0.95
                pixels[idx] = int(hr * blend + pixels[idx] * (1 - blend))
                pixels[idx + 1] = int(hg * blend + pixels[idx + 1] * (1 - blend))
                pixels[idx + 2] = int(hb * blend + pixels[idx + 2] * (1 - blend))

    return pixels


def create_ico(png_data_list):
    """Create ICO file from multiple PNG data entries.
    png_data_list: list of (size, png_bytes) tuples
    """
    num = len(png_data_list)
    # ICO header: reserved(2) + type(2) + count(2)
    header = struct.pack("<HHH", 0, 1, num)

    # Directory entries + PNG data
    entries = b''
    data = b''
    offset = 6 + num * 16  # header + all directory entries

    for size, png_bytes in png_data_list:
        w = size if size < 256 else 0
        h = size if size < 256 else 0
        entry = struct.pack("<BBBBHHII",
                            w, h,  # width, height (0 = 256)
                            0,     # color palette
                            0,     # reserved
                            1,     # color planes
                            32,    # bits per pixel
                            len(png_bytes),  # size of data
                            offset)          # offset of data
        entries += entry
        data += png_bytes
        offset += len(png_bytes)

    return header + entries + data


def main():
    os.makedirs(ICON_DIR, exist_ok=True)

    sizes = [16, 24, 32, 48, 64, 128, 256]
    png_for_ico = []

    print("Generating Helen WiFi icons...")

    for size in sizes:
        print(f"  Drawing {size}x{size}...", end=" ", flush=True)
        pixels = draw_icon(size)
        png_bytes = create_png(size, size, pixels)
        png_for_ico.append((size, png_bytes))

        # Save individual PNGs
        png_path = os.path.join(ICON_DIR, f"icon_{size}x{size}.png")
        with open(png_path, "wb") as f:
            f.write(png_bytes)
        print(f"OK ({len(png_bytes)} bytes)")

    # Save main icon.png (256x256)
    main_png = os.path.join(ICON_DIR, "icon.png")
    with open(main_png, "wb") as f:
        f.write(png_for_ico[-1][1])  # 256x256
    print(f"\n  Main PNG: {main_png}")

    # Create ICO with multiple sizes
    ico_bytes = create_ico(png_for_ico)
    ico_path = os.path.join(ICON_DIR, "icon.ico")
    with open(ico_path, "wb") as f:
        f.write(ico_bytes)
    print(f"  ICO file: {ico_path} ({len(ico_bytes)} bytes)")

    # Also create tray icon (small, 24x24)
    tray_png = os.path.join(ICON_DIR, "tray.png")
    with open(tray_png, "wb") as f:
        f.write(png_for_ico[1][1])  # 24x24
    print(f"  Tray PNG: {tray_png}")

    # Create macOS ICNS-compatible 512x512
    print(f"  Drawing 512x512...", end=" ", flush=True)
    pixels_512 = draw_icon(512)
    png_512 = create_png(512, 512, pixels_512)
    with open(os.path.join(ICON_DIR, "icon_512x512.png"), "wb") as f:
        f.write(png_512)
    print(f"OK ({len(png_512)} bytes)")

    print(f"\n  All icons generated in: {ICON_DIR}")
    print("  Done!")


if __name__ == "__main__":
    main()
