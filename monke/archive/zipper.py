"""Zip writing (ARC-8). Separate from the builder so the builder stays a pure dict-of-bytes function.
Deterministic: fixed timestamps, sorted entries, fixed compression."""
from __future__ import annotations

import io
import zipfile
import zlib

_FIXED_DATE = (2000, 1, 1, 0, 0, 0)
_PER_FILE_OVERHEAD = 200  # generous allowance for local header + central directory entry


def _csize(data: bytes) -> int:
    c = zlib.compressobj(6, zlib.DEFLATED, -15)
    return len(c.compress(data)) + len(c.flush())


def _split_lines(name: str, data: bytes, budget: int) -> list:
    """Split one oversized text file at line boundaries until every piece compresses under `budget`."""
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    lines = data.splitlines(keepends=True)
    pieces: list = []

    def rec(chunk: list) -> None:
        blob = b"".join(chunk)
        if len(chunk) <= 1 or _csize(blob) + _PER_FILE_OVERHEAD <= budget:
            pieces.append(blob)
            return
        mid = len(chunk) // 2
        rec(chunk[:mid])
        rec(chunk[mid:])

    rec(lines)
    return [(f"{stem}.part{i:02d}{'.' + ext if ext else ''}", blob) for i, blob in enumerate(pieces, 1)]


def _zip_bytes(entries: list) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=_FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
    return buf.getvalue()


def write_zips(files: dict, base_name: str, limit_bytes: int) -> list:
    """Returns [(zip_filename, zip_bytes)]. One zip if it fits under `limit_bytes`; otherwise several,
    split at file boundaries (`part1of2`), and a single file that is itself too big is split at line
    boundaries."""
    budget = int(limit_bytes * 0.9)
    for _ in range(6):  # tighten the budget if a zip still lands over the limit
        entries: list = []
        for name in sorted(files):
            data = files[name]
            if _csize(data) + _PER_FILE_OVERHEAD > budget:
                entries.extend(_split_lines(name, data, budget))
            else:
                entries.append((name, data))
        groups: list = [[]]
        used = 0
        for name, data in entries:
            c = _csize(data) + _PER_FILE_OVERHEAD
            if groups[-1] and used + c > budget:
                groups.append([])
                used = 0
            groups[-1].append((name, data))
            used += c
        out = []
        for i, g in enumerate(groups, 1):
            fname = f"{base_name}.zip" if len(groups) == 1 else f"{base_name}.part{i}of{len(groups)}.zip"
            out.append((fname, _zip_bytes(g)))
        if all(len(b) <= limit_bytes for _, b in out):
            return out
        budget = int(budget * 0.8)
    return out
