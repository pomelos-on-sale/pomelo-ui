#!/usr/bin/env python3
"""
tools/png_to_qoi.py
Converts images (PNG, JPG, etc.) into the Quite OK Image (QOI) format for Pomelo OS.

Features:
- Self-contained, zero-dependency pure Python QOI encoder (only requires Pillow).
- High-quality Lanczos resampling and center cropping.
- Optional 16-sample supersampled iOS-style Squircle (continuous-curvature) rounded corner mask.
- Directly configured in main() via variables (no command-line arguments needed).
"""

import os
import sys
import math
import struct
import time

try:
    from PIL import Image
except ImportError:
    print("[!] Error: 'Pillow' is required.")
    print("    Install it via: pip install Pillow")
    sys.exit(1)


# =============================================================================
# QOI Encoder Implementation (Pure Python, Full Specification Compliant)
# =============================================================================

QOI_OP_INDEX = 0x00  # 00xxxxxx
QOI_OP_DIFF  = 0x40  # 01xxxxxx
QOI_OP_LUMA  = 0x80  # 10xxxxxx
QOI_OP_RUN   = 0xC0  # 11xxxxxx
QOI_OP_RGB   = 0xFE  # 11111110
QOI_OP_RGBA  = 0xFF  # 11111111

QOI_MAGIC = b"qoif"
QOI_END_MARKER = b"\x00\x00\x00\x00\x00\x00\x00\x01"


def encode_qoi(width: int, height: int, pixels: bytes, channels: int = 4, colorspace: int = 0) -> bytes:
    """
    Encodes raw pixel bytes (RGB or RGBA) into QOI format bytes.
    - width, height: image dimensions in pixels
    - pixels: bytes sequence of length width * height * channels
    - channels: 3 for RGB, 4 for RGBA
    - colorspace: 0 for sRGB with linear alpha
    """
    if channels not in (3, 4):
        raise ValueError(f"Invalid channels: {channels}. Must be 3 (RGB) or 4 (RGBA).")

    out = bytearray(QOI_MAGIC)
    out.extend(struct.pack(">IIBB", width, height, channels, colorspace))

    index = [[0, 0, 0, 0] for _ in range(64)]
    prev_r, prev_g, prev_b, prev_a = 0, 0, 0, 255
    run = 0

    total_pixels = width * height
    stride = channels

    for i in range(0, total_pixels * stride, stride):
        r = pixels[i]
        g = pixels[i + 1]
        b = pixels[i + 2]
        a = pixels[i + 3] if channels == 4 else 255

        if r == prev_r and g == prev_g and b == prev_b and a == prev_a:
            run += 1
            if run == 62:
                out.append(QOI_OP_RUN | (run - 1))
                run = 0
        else:
            if run > 0:
                out.append(QOI_OP_RUN | (run - 1))
                run = 0

            idx = (r * 3 + g * 5 + b * 7 + a * 11) % 64
            if index[idx] == [r, g, b, a]:
                out.append(QOI_OP_INDEX | idx)
            elif a == prev_a:
                vr = (r - prev_r)
                vg = (g - prev_g)
                vb = (b - prev_b)
                # Wraparound handling for 8-bit difference
                if vr > 127: vr -= 256
                elif vr < -128: vr += 256
                if vg > 127: vg -= 256
                elif vg < -128: vg += 256
                if vb > 127: vb -= 256
                elif vb < -128: vb += 256

                vg_r = vr - vg
                vg_b = vb - vg

                if -2 <= vr <= 1 and -2 <= vg <= 1 and -2 <= vb <= 1:
                    out.append(QOI_OP_DIFF | ((vr + 2) << 4) | ((vg + 2) << 2) | (vb + 2))
                elif -32 <= vg <= 31 and -8 <= vg_r <= 7 and -8 <= vg_b <= 7:
                    out.append(QOI_OP_LUMA | (vg + 32))
                    out.append(((vg_r + 8) << 4) | (vg_b + 8))
                else:
                    out.extend([QOI_OP_RGB, r, g, b])
            else:
                out.extend([QOI_OP_RGBA, r, g, b, a])

            index[idx] = [r, g, b, a]
            prev_r, prev_g, prev_b, prev_a = r, g, b, a

    if run > 0:
        out.append(QOI_OP_RUN | (run - 1))

    out.extend(QOI_END_MARKER)
    return bytes(out)


# =============================================================================
# Squircle Mask Generator
# =============================================================================

def generate_squircle_mask(size: int, radius_ratio: float = 0.225) -> list:
    """
    Generates a per-pixel squircle alpha mask for an icon of size x size pixels,
    using 4x supersampling (16 samples per pixel) for GPU-quality antialiasing.
    Apple iOS standard continuous curvature uses ~22.5% of side length.
    """
    supersample = 4
    samples = float(supersample * supersample)
    mask = [0] * (size * size)
    half = size * 0.5
    corner_r = radius_ratio * size
    inner = half - corner_r

    for y in range(size):
        for x in range(size):
            coverage = 0.0
            for sy in range(supersample):
                sub_y = y + (sy + 0.5) / supersample
                dy = abs(sub_y - half)
                qy = max(dy - inner, 0.0)

                for sx in range(supersample):
                    sub_x = x + (sx + 0.5) / supersample
                    dx = abs(sub_x - half)
                    qx = max(dx - inner, 0.0)
                    dist = math.hypot(qx, qy)

                    if dist <= corner_r - 1.0:
                        coverage += 1.0
                    elif dist < corner_r:
                        coverage += corner_r - dist

            mask[y * size + x] = min(255, max(0, int((coverage / samples) * 255.0 + 0.5)))

    return mask


# =============================================================================
# Image Processing & Conversion Function
# =============================================================================

def convert_image_to_qoi(
    input_path: str,
    output_path: str,
    target_size: tuple = None,
    crop_mode: str = "square",
    squircle: bool = False,
    squircle_radius_ratio: float = 0.225,
) -> None:
    """
    Reads an image, crops/resizes it, optionally applies squircle rounded corners,
    and encodes it into a QOI file.

    Parameters:
    - input_path: path to input image (PNG, JPG, etc.)
    - output_path: destination path for .qoi file
    - target_size: (width, height) tuple, or None to keep original size
    - crop_mode: 'square' for central square crop, 'aspect' for aspect ratio crop, or 'none'
    - squircle: whether to apply continuous-curvature rounded corner alpha mask
    - squircle_radius_ratio: corner radius ratio (default 0.225 for iOS squircle)
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    t_start = time.time()
    orig_img = Image.open(input_path)
    orig_w, orig_h = orig_img.size

    # Convert to RGBA for processing
    img = orig_img.convert("RGBA")

    # 1. Cropping
    if crop_mode == "square":
        crop_size = min(orig_w, orig_h)
        left = (orig_w - crop_size) // 2
        top = (orig_h - crop_size) // 2
        img = img.crop((left, top, left + crop_size, top + crop_size))
    elif crop_mode == "aspect" and target_size:
        target_w, target_h = target_size
        target_ratio = target_w / target_h
        orig_ratio = orig_w / orig_h
        if orig_ratio > target_ratio:
            # Source is wider than target: crop width
            new_w = int(orig_h * target_ratio)
            left = (orig_w - new_w) // 2
            img = img.crop((left, 0, left + new_w, orig_h))
        else:
            # Source is taller than target: crop height
            new_h = int(orig_w / target_ratio)
            top = (orig_h - new_h) // 2
            img = img.crop((0, top, orig_w, top + new_h))

    # 2. Resampling / Resizing
    lanczos = getattr(Image, "Resampling", Image).LANCZOS
    if target_size:
        img = img.resize(target_size, lanczos)

    final_w, final_h = img.size
    raw_bytes = bytearray(img.tobytes())

    # 3. Squircle rounded corners
    channels = 4
    if squircle:
        if final_w != final_h:
            raise ValueError(f"Squircle mask requires a square image, got {final_w}x{final_h}")
        mask = generate_squircle_mask(final_w, squircle_radius_ratio)
        for idx in range(final_w * final_h):
            orig_alpha = raw_bytes[idx * 4 + 3]
            sq_alpha = mask[idx]
            raw_bytes[idx * 4 + 3] = (orig_alpha * sq_alpha) // 255
    else:
        # If no squircle and image is completely opaque, encode as 3-channel RGB to save space
        has_transparency = any(raw_bytes[i * 4 + 3] < 255 for i in range(final_w * final_h))
        if not has_transparency:
            channels = 3
            rgb_bytes = bytearray(final_w * final_h * 3)
            for idx in range(final_w * final_h):
                rgb_bytes[idx * 3]     = raw_bytes[idx * 4]
                rgb_bytes[idx * 3 + 1] = raw_bytes[idx * 4 + 1]
                rgb_bytes[idx * 3 + 2] = raw_bytes[idx * 4 + 2]
            raw_bytes = rgb_bytes

    # 4. QOI Encoding
    qoi_data = encode_qoi(final_w, final_h, bytes(raw_bytes), channels=channels)

    # 5. Output
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(qoi_data)

    elapsed_ms = (time.time() - t_start) * 1000
    in_size_kb = os.path.getsize(input_path) / 1024
    out_size_kb = len(qoi_data) / 1024

    print(f"[*] Converted: {os.path.basename(input_path)} -> {os.path.basename(output_path)}")
    print(f"    Dimensions : {orig_w}x{orig_h} -> {final_w}x{final_h} ({channels} channels)")
    print(f"    Squircle   : {'Yes (16-sample AA)' if squircle else 'No'}")
    print(f"    File size  : {in_size_kb:.1f} KB -> {out_size_kb:.1f} KB (elapsed: {elapsed_ms:.1f} ms)")


# =============================================================================
# Main Entry Point (Define tasks and parameters directly in code)
# =============================================================================

def main():
    workspace_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    print("=== Converting Pomelo OS Assets to QOI ===")

    # -------------------------------------------------------------------------
    # 任务 1: Hello 应用图标
    # - 目标尺寸: 118x118
    # - 裁剪模式: 居中正方形裁剪 (square)
    # - 倒角效果: 开启 iOS 平滑连续曲率超采样倒角 (Squircle)
    # -------------------------------------------------------------------------
    hello_input_path = os.path.join(workspace_root, "assets", "app-icons", "hello.png")
    hello_output_path = os.path.join(workspace_root, "assets", "app-icons", "hello.qoi")
    hello_target_size = (118, 118)
    hello_crop_mode = "square"
    hello_squircle = True
    hello_radius_ratio = 0.225

    convert_image_to_qoi(
        input_path=hello_input_path,
        output_path=hello_output_path,
        target_size=hello_target_size,
        crop_mode=hello_crop_mode,
        squircle=hello_squircle,
        squircle_radius_ratio=hello_radius_ratio,
    )

    # -------------------------------------------------------------------------
    # 任务 2: 峡湾极光与星空壁纸 (Aurora Borealis)
    # - 目标尺寸: 480x430 (匹配物理屏幕分辨率)
    # - 裁剪模式: 等比缩放居中裁剪 (aspect)
    # - 倒角效果: 关闭倒角 (直角全屏铺满)
    # -------------------------------------------------------------------------
    aurora_input_path = os.path.join(workspace_root, "assets", "image", "wallpaper_aurora.jpg")
    aurora_output_path = os.path.join(workspace_root, "assets", "image", "wallpaper_aurora.qoi")
    aurora_target_size = (480, 430)
    aurora_crop_mode = "aspect"
    aurora_squircle = False

    if os.path.exists(aurora_input_path):
        convert_image_to_qoi(
            input_path=aurora_input_path,
            output_path=aurora_output_path,
            target_size=aurora_target_size,
            crop_mode=aurora_crop_mode,
            squircle=aurora_squircle,
        )

    # -------------------------------------------------------------------------
    # 任务 3: 金色银河星空壁纸 (Golden Night Milky Way - Unsplash CC0)
    # - 目标尺寸: 480x430 (匹配物理屏幕分辨率)
    # - 裁剪模式: 等比缩放居中裁剪 (aspect)
    # - 倒角效果: 关闭倒角 (直角全屏铺满)
    # -------------------------------------------------------------------------
    milkyway_input_path = os.path.join(workspace_root, "assets", "image", "wallpaper_milkyway.jpg")
    milkyway_output_path = os.path.join(workspace_root, "assets", "image", "wallpaper_milkyway.qoi")
    milkyway_target_size = (480, 430)
    milkyway_crop_mode = "aspect"
    milkyway_squircle = False

    if os.path.exists(milkyway_input_path):
        convert_image_to_qoi(
            input_path=milkyway_input_path,
            output_path=milkyway_output_path,
            target_size=milkyway_target_size,
            crop_mode=milkyway_crop_mode,
            squircle=milkyway_squircle,
        )

    print("[+] All image conversion tasks completed successfully.")


if __name__ == "__main__":
    main()
