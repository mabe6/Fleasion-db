"""Export hash-named Roblox cache files for offline format analysis."""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

_HASH_FILENAME_RE = re.compile(r"^(?:[0-9a-f]{32}|[0-9a-f]{64})(?:\.[a-z0-9]{1,12})?$", re.I)
_IGNORED_DIRECTORIES = {".git", ".venv", "venv", "__pycache__", "node_modules"}


class HashFileDumpError(RuntimeError):
    """A user-displayable error from exporting hash-named files."""


def _safe_url(value: str) -> str:
    """Keep the CDN path but omit signed query parameters from the dump manifest."""
    try:
        parsed = urlsplit(str(value or ""))
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    except ValueError:
        return ""


def _cache_root_for_folder(folder: Path) -> Path | None:
    """Recognize either a Roblox cache root or its rbx-storage subfolder."""
    if (folder / "rbx-storage.db").is_file():
        return folder
    if folder.name.casefold() == "rbx-storage" and (folder.parent / "rbx-storage.db").is_file():
        return folder.parent
    return None


def _hash_named_files(folder: Path) -> list[Path]:
    result: list[Path] = []
    for current, directories, filenames in os.walk(folder, followlinks=False):
        current_path = Path(current)
        directories[:] = [
            name for name in directories
            if name not in _IGNORED_DIRECTORIES
            and not (current_path / name).is_symlink()
        ]
        for filename in filenames:
            candidate = current_path / filename
            if candidate.is_symlink() or not _HASH_FILENAME_RE.fullmatch(filename):
                continue
            try:
                if candidate.is_file():
                    result.append(candidate)
            except OSError:
                continue
    result.sort(key=lambda item: str(item.relative_to(folder)).casefold())
    return result


def _unique_dump_directory(output_parent: Path) -> Path:
    output_parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base = output_parent / f"Fleasion_HashDump_{timestamp}"
    candidate = base
    suffix = 2
    while candidate.exists():
        candidate = output_parent / f"{base.name}_{suffix}"
        suffix += 1
    candidate.mkdir()
    return candidate


def dump_hash_files_from_folder(
    source_folder: str | os.PathLike[str],
    output_parent: str | os.PathLike[str],
) -> dict:
    """Copy hashed cache files/payloads into a clean dump folder with a manifest.

    If the selected folder is a Roblox cache root (or its rbx-storage child),
    the SQLite index is used and each entry is exported as its raw payload with
    the RBXH wrapper removed. Otherwise, recursively copy files whose names are
    32- or 64-character hexadecimal hashes, preserving their relative paths.
    Original files are never modified.
    """
    source = Path(source_folder).expanduser().resolve()
    destination = Path(output_parent).expanduser().resolve()
    if not source.is_dir():
        raise HashFileDumpError(f"Source folder does not exist: {source}")
    try:
        destination.relative_to(source)
    except ValueError:
        pass
    else:
        raise HashFileDumpError(
            "Choose an output folder outside the source folder to avoid exporting the dump into itself."
        )

    cache_root = _cache_root_for_folder(source)
    dump_dir = _unique_dump_directory(destination)
    files: list[dict] = []
    errors: list[str] = []
    total_bytes = 0
    type_counts: dict[str, int] = {}

    if cache_root is not None:
        from .roblox_cache_store import (
            RobloxCacheError,
            RobloxCacheStore,
            detect_roblox_cache_payload_kind,
        )

        store = RobloxCacheStore(cache_root)
        try:
            entries = store.scan(limit=1_000_000)
            if not entries:
                raise HashFileDumpError("The selected Roblox cache contains no exportable hash entries.")
            payload_dir = dump_dir / "payloads"
            payload_dir.mkdir()
            for entry in entries:
                relative = Path("payloads") / f"{entry.entry_id}.bin"
                target = dump_dir / relative
                try:
                    url, size = store.copy_entry_payload_to_file(entry.entry_id, target)
                    with target.open("rb") as handle:
                        sample = handle.read(8192)
                    kind = detect_roblox_cache_payload_kind(sample, url=url or entry.url)
                    files.append({
                        "cache_hash": entry.entry_id,
                        "file": relative.as_posix(),
                        "kind": kind,
                        "source_kind": entry.kind,
                        "asset_id": entry.asset_id or "",
                        "url": _safe_url(url or entry.url),
                        "storage_mode": entry.storage_mode,
                        "payload_size": size,
                        "rbxh_header_removed": bool(entry.has_rbxh_header),
                    })
                    total_bytes += size
                    type_counts[kind] = type_counts.get(kind, 0) + 1
                except (OSError, RobloxCacheError) as exc:
                    target.unlink(missing_ok=True)
                    errors.append(f"{entry.entry_id}: {type(exc).__name__}: {exc}")
        except (OSError, RobloxCacheError) as exc:
            shutil.rmtree(dump_dir, ignore_errors=True)
            raise HashFileDumpError(str(exc)) from exc
        source_mode = "roblox-cache-database"
        source_label = cache_root.name
    else:
        candidates = _hash_named_files(source)
        if not candidates:
            shutil.rmtree(dump_dir, ignore_errors=True)
            raise HashFileDumpError(
                "No files with 32-character cache hashes or 64-character SHA-256 names were found."
            )
        for candidate in candidates:
            relative_source = candidate.relative_to(source)
            relative_dump = Path("files") / relative_source
            target = dump_dir / relative_dump
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(candidate, target)
                with candidate.open("rb") as handle:
                    sample = handle.read(8192)
                url = ""
                payload_sample = sample
                try:
                    from .roblox_cache_store import split_rbxh_entry, detect_roblox_cache_payload_kind

                    url, payload_sample, _has_header = split_rbxh_entry(sample)
                    kind = detect_roblox_cache_payload_kind(payload_sample, url=url)
                except Exception:
                    from .roblox_cache_store import detect_roblox_cache_payload_kind

                    kind = detect_roblox_cache_payload_kind(payload_sample)
                size = candidate.stat().st_size
                files.append({
                    "file": relative_dump.as_posix(),
                    "original_relative_path": relative_source.as_posix(),
                    "kind": kind,
                    "source_name": candidate.name,
                    "size": size,
                    "url": _safe_url(url),
                    "copied_exactly": True,
                })
                total_bytes += size
                type_counts[kind] = type_counts.get(kind, 0) + 1
            except OSError as exc:
                target.unlink(missing_ok=True)
                errors.append(f"{relative_source}: {type(exc).__name__}: {exc}")

        source_mode = "hash-named-files"
        source_label = source.name

    if not files:
        shutil.rmtree(dump_dir, ignore_errors=True)
        details = " | ".join(errors[:8])
        raise HashFileDumpError(
            "No hash files could be exported." + (f" {details}" if details else "")
        )

    manifest = {
        "format": "Fleasion hash-file dump",
        "format_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_folder": source_label,
        "source_mode": source_mode,
        "file_count": len(files),
        "total_bytes": total_bytes,
        "detected_types": dict(sorted(type_counts.items())),
        "errors": errors,
        "files": files,
    }
    (dump_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "output_folder": dump_dir,
        "file_count": len(files),
        "total_bytes": total_bytes,
        "detected_types": dict(sorted(type_counts.items())),
        "errors": errors,
        "source_mode": source_mode,
    }
