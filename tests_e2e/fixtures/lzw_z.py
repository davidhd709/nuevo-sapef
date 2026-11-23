"""Genuine Unix compress (.Z, magic 0x1F 0x9D) LZW encoder and decoder.

Implements standard POSIX compress block-mode LZW (9..16 bits, LSB-first packing,
n_bits-byte group boundaries) so Afinia .Z ingestion tests pass authentic .Z archives.
"""

from __future__ import annotations

_MAGIC = b"\x1f\x9d"
_BLOCK_MASK = 0x80
_CLEAR_CODE = 256


def compress_z(data: bytes, *, max_bits: int = 16, block_mode: bool = True) -> bytes:
    """Compress raw bytes into a valid Unix .Z (LZW) archive."""
    if not 9 <= max_bits <= 16:
        raise ValueError(f"max_bits must be between 9 and 16, got {max_bits}")

    flags = max_bits | (_BLOCK_MASK if block_mode else 0)
    out = bytearray(_MAGIC)
    out.append(flags)

    if not data:
        return bytes(out)

    n_bits = 9
    maxcode = (1 << n_bits) - 1
    maxmaxcode = 1 << max_bits
    first_free = 257 if block_mode else 256
    free_ent = first_free

    table: dict[tuple[int, int], int] = {}
    bit_buf = bytearray(n_bits)
    bit_offset = 0

    def _flush_group() -> None:
        """Flush a full n_bits-byte group on bit-width bump or CLEAR (POSIX compress)."""
        nonlocal bit_offset
        if bit_offset > 0:
            out.extend(bit_buf)
            bit_offset = 0
            for idx in range(len(bit_buf)):
                bit_buf[idx] = 0

    def _flush_eof() -> None:
        """Flush only occupied bytes at EOF."""
        nonlocal bit_offset
        if bit_offset > 0:
            nbytes = (bit_offset + 7) // 8
            out.extend(bit_buf[:nbytes])
            bit_offset = 0

    def _emit_code(code: int) -> None:
        nonlocal bit_offset, bit_buf
        r_off = bit_offset
        bits_left = n_bits
        byte_idx = r_off >> 3
        bit_in_byte = r_off & 7

        if bit_in_byte:
            space = 8 - bit_in_byte
            bit_buf[byte_idx] |= (code << bit_in_byte) & 0xFF
            code >>= space
            bits_left -= space
            byte_idx += 1

        while bits_left >= 8:
            bit_buf[byte_idx] = code & 0xFF
            code >>= 8
            bits_left -= 8
            byte_idx += 1

        if bits_left > 0:
            bit_buf[byte_idx] = code & ((1 << bits_left) - 1)

        bit_offset += n_bits
        if bit_offset == n_bits * 8:
            out.extend(bit_buf)
            bit_buf = bytearray(n_bits)
            bit_offset = 0

    ent = data[0]
    for byte in data[1:]:
        pair = (ent, byte)
        nxt = table.get(pair)
        if nxt is not None:
            ent = nxt
            continue

        _emit_code(ent)
        if free_ent > maxcode:
            _flush_group()
            if free_ent >= maxmaxcode and block_mode:
                _emit_code(_CLEAR_CODE)
                _flush_group()
                table.clear()
                n_bits = 9
                maxcode = (1 << n_bits) - 1
                free_ent = first_free
                bit_buf = bytearray(n_bits)
            elif n_bits < max_bits:
                n_bits += 1
                maxcode = (1 << n_bits) - 1 if n_bits < max_bits else maxmaxcode
                bit_buf = bytearray(n_bits)

        if free_ent < maxmaxcode:
            table[pair] = free_ent
            free_ent += 1

        ent = byte

    _emit_code(ent)
    _flush_eof()
    return bytes(out)


def decompress_z(blob: bytes) -> bytes:
    """Decompress a Unix .Z (LZW) archive back to raw bytes."""
    if len(blob) < 3 or blob[:2] != _MAGIC:
        raise ValueError("Invalid .Z magic header (expected 0x1F 0x9D)")

    flags = blob[2]
    max_bits = flags & 0x1F
    block_mode = bool(flags & _BLOCK_MASK)
    if not 9 <= max_bits <= 16:
        raise ValueError(f"Unsupported .Z max_bits={max_bits}")

    pos = 3
    if pos >= len(blob):
        return b""

    n_bits = 9
    maxcode = (1 << n_bits) - 1
    maxmaxcode = 1 << max_bits
    first_free = 257 if block_mode else 256
    free_ent = first_free

    prefix = [0] * maxmaxcode
    suffix = [0] * maxmaxcode
    for i in range(256):
        suffix[i] = i

    chunk = b""
    chunk_bits = 0
    bit_off = 0

    def _next_code() -> int | None:
        nonlocal pos, chunk, chunk_bits, bit_off, n_bits, maxcode
        if bit_off + n_bits > chunk_bits:
            if pos >= len(blob):
                return None
            take = min(n_bits, len(blob) - pos)
            chunk = blob[pos : pos + take]
            pos += take
            chunk_bits = take * 8
            bit_off = 0
            if chunk_bits < n_bits:
                return None

        byte_idx = bit_off >> 3
        r_bit = bit_off & 7
        val = chunk[byte_idx] >> r_bit
        bits_got = 8 - r_bit
        byte_idx += 1
        while bits_got < n_bits:
            val |= chunk[byte_idx] << bits_got
            bits_got += 8
            byte_idx += 1
        bit_off += n_bits
        return val & ((1 << n_bits) - 1)

    first = _next_code()
    if first is None:
        return b""
    if first > 255:
        raise ValueError(f"Corrupt .Z stream: initial code {first} > 255")

    oldcode = first
    finchar = first
    out = bytearray([finchar])

    while True:
        code = _next_code()
        if code is None:
            break

        if block_mode and code == _CLEAR_CODE:
            free_ent = first_free
            n_bits = 9
            maxcode = (1 << n_bits) - 1
            chunk_bits = 0
            bit_off = 0
            nxt = _next_code()
            if nxt is None:
                break
            oldcode = nxt
            finchar = nxt
            out.append(finchar)
            continue

        incode = code
        stack: list[int] = []
        if code >= free_ent:
            if code > free_ent:
                raise ValueError(f"Corrupt .Z stream: invalid LZW code {code} > {free_ent}")
            stack.append(finchar)
            code = oldcode

        while code >= 256:
            stack.append(suffix[code])
            code = prefix[code]

        finchar = suffix[code]
        stack.append(finchar)
        out.extend(reversed(stack))

        if free_ent < maxmaxcode:
            prefix[free_ent] = oldcode
            suffix[free_ent] = finchar
            free_ent += 1
            if free_ent > maxcode and n_bits < max_bits:
                n_bits += 1
                maxcode = (1 << n_bits) - 1 if n_bits < max_bits else maxmaxcode
                chunk_bits = 0
                bit_off = 0

        oldcode = incode

    return bytes(out)
