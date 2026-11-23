"""Synthetic media/document binary payload builders with authentic magic headers.

Provides valid minimal PNG, JPEG, WebP, PDF, and MP4/AAC payloads plus forged MIME
and oversized payloads for HTTP 415/413 validation tests.
"""

from __future__ import annotations

import struct
import zlib


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack("!I", len(data)) + chunk_type + data + struct.pack("!I", crc)


def make_png(width: int = 2, height: int = 2) -> bytes:
    """Create a valid minimal RGB PNG file."""
    ihdr = struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw_scanlines = b"".join(b"\x00" + (b"\x20\x90\xe0" * width) for _ in range(height))
    idat = zlib.compress(raw_scanlines)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


def make_jpeg() -> bytes:
    """Create a minimal valid JFIF JPEG header + SOF0 + EOI sequence."""
    app0_jfif = (
        b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    )
    sof0 = b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    sos = b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\xd2\xcf\x20"
    return b"\xff\xd8" + app0_jfif + sof0 + sos + b"\xff\xd9"


def make_webp() -> bytes:
    """Create a minimal valid RIFF WEBP VP8 container."""
    vp8_bitstream = b"\x30\x01\x00\x9d\x01\x2a\x01\x00\x01\x00\x00\x34\x25\xa4\x00\x03\x70\x00\xfe"
    if len(vp8_bitstream) % 2 == 1:
        vp8_bitstream += b"\x00"
    vp8_chunk = b"VP8 " + struct.pack("<I", len(vp8_bitstream)) + vp8_bitstream
    riff_body = b"WEBP" + vp8_chunk
    return b"RIFF" + struct.pack("<I", len(riff_body)) + riff_body


def make_pdf(text: str = "SAPEF E2E Test Document") -> bytes:
    """Create a minimal valid PDF 1.4 document with cross-reference table."""
    safe_text = text.replace("(", "\\(").replace(")", "\\)")
    stream_body = f"BT /F1 12 Tf 72 720 Td ({safe_text}) Tj ET".encode("latin-1", errors="replace")
    objs = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
        ),
        (
            f"4 0 obj\n<< /Length {len(stream_body)} >>\nstream\n".encode("ascii")
            + stream_body
            + b"\nendstream\nendobj\n"
        ),
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = [0]
    for obj in objs:
        offsets.append(len(out))
        out.extend(obj)
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(out)


def make_mp4_aac() -> bytes:
    """Create a minimal ISO Base Media (MP4/M4A) container with ftyp + mvhd + mdat."""
    ftyp_body = b"M4A \x00\x00\x00\x00M4A mp42isom"
    ftyp = struct.pack(">I", 8 + len(ftyp_body)) + b"ftyp" + ftyp_body
    mvhd = struct.pack(">I", 16) + b"free" + b"\x00" * 8
    mdat_payload = b"\x21\x10\x04\x60\x8c\x1c"
    mdat = struct.pack(">I", 8 + len(mdat_payload)) + b"mdat" + mdat_payload
    return ftyp + mvhd + mdat


def make_forged_file(
    claimed_filename: str = "evidencia.jpg",
    *,
    actual_kind: str = "exe",
    claimed_mime: str = "image/jpeg",
) -> tuple[str, bytes, str]:
    """Return (filename, forged_bytes, claimed_mime) whose magic bytes do not match claimed type."""
    if actual_kind == "pdf":
        payload = make_pdf("Forged inside image extension")
    elif actual_kind == "elf":
        payload = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 32
    else:
        payload = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff" + b"\x00" * 32
    return (claimed_filename, payload, claimed_mime)


def make_oversized_payload(size_bytes: int, *, magic: bytes = b"\x89PNG\r\n\x1a\n") -> bytes:
    """Return a payload of exact size_bytes starting with magic header (for 413 tests)."""
    if size_bytes <= len(magic):
        return magic[:size_bytes]
    return magic + (b"\x00" * (size_bytes - len(magic)))
