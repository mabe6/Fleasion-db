import json
import sqlite3
import struct
from pathlib import Path

from fleasion.database.hash_file_dump import (
    HashFileDumpError,
    dump_hash_files_from_folder,
)
from fleasion.database import roblox_cache_store as store_module
from fleasion.database import sqlite_browser as sqlite_browser_module


def _rbxh(url: str, payload: bytes) -> bytes:
    encoded_url = url.encode("utf-8")
    header = bytearray(
        b"RBXH" + b"\x00" * 4 + struct.pack("<I", len(encoded_url))
    )
    header.extend(encoded_url)
    header.extend(b"\x00" * 25)
    struct.pack_into("<I", header, len(header) - 25, len(payload))
    return bytes(header) + payload


def _make_cache_root(tmp_path: Path, monkeypatch, entries: dict[str, bytes]) -> Path:
    root = tmp_path / "Roblox"
    assets = root / "rbx-storage"
    assets.mkdir(parents=True)
    with sqlite3.connect(root / "rbx-storage.db") as connection:
        connection.execute(
            "CREATE TABLE files (id BLOB PRIMARY KEY, size INTEGER NOT NULL)"
        )
        for entry_id, content in entries.items():
            file_path = assets / entry_id[:2] / entry_id
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(content)
            connection.execute(
                "INSERT INTO files (id, size) VALUES (?, ?)",
                (bytes.fromhex(entry_id), len(content)),
            )

    config_dir = tmp_path / "app-config"
    monkeypatch.setattr(store_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(sqlite_browser_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(store_module, "_is_roblox_process_running", lambda: False)
    return root


def test_dump_roblox_cache_root_exports_payloads_and_manifest(tmp_path, monkeypatch):
    png_id = "a" * 32
    csg_id = "b" * 32
    png = b"\x89PNG\r\n\x1a\n" + b"png-fixture"
    csg = b"CSGPHS" + struct.pack("<I", 8) + b"\x00" * 80
    root = _make_cache_root(
        tmp_path,
        monkeypatch,
        {
            png_id: _rbxh(
                "https://fts.rbxcdn.com/sc3/" + "1a" * 16 + "?token=temporary",
                png,
            ),
            csg_id: _rbxh("https://fts.rbxcdn.com/sc7/" + "2b" * 16, csg),
        },
    )

    report = dump_hash_files_from_folder(root, tmp_path / "exports")

    output = Path(report["output_folder"])
    assert report["file_count"] == 2
    assert report["source_mode"] == "roblox-cache-database"
    assert (output / "payloads" / f"{png_id}.bin").read_bytes() == png
    assert (output / "payloads" / f"{csg_id}.bin").read_bytes() == csg

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["file_count"] == 2
    by_id = {item["cache_hash"]: item for item in manifest["files"]}
    assert by_id[png_id]["kind"] == "png"
    assert by_id[csg_id]["kind"] == "csgphs"
    assert by_id[png_id]["rbxh_header_removed"] is True
    assert "token=" not in by_id[png_id]["url"]


def test_dump_plain_hash_folder_recurses_and_preserves_exact_bytes(tmp_path):
    source = tmp_path / "hashes"
    nested = source / "aa"
    nested.mkdir(parents=True)
    cache_hash_file = nested / ("a" * 32)
    sha_file = source / (("b" * 64) + ".rbxm")
    ignored = nested / "not-a-hash.bin"
    cache_data = b"raw-cache-file\x00\x01"
    sha_data = b"<roblox version='4'/>"
    cache_hash_file.write_bytes(cache_data)
    sha_file.write_bytes(sha_data)
    ignored.write_bytes(b"ignore me")

    report = dump_hash_files_from_folder(source, tmp_path / "exports")

    output = Path(report["output_folder"])
    assert report["file_count"] == 2
    assert report["source_mode"] == "hash-named-files"
    assert (output / "files" / "aa" / cache_hash_file.name).read_bytes() == cache_data
    assert (output / "files" / sha_file.name).read_bytes() == sha_data
    assert not (output / "files" / "aa" / ignored.name).exists()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert {item["source_name"] for item in manifest["files"]} == {
        cache_hash_file.name,
        sha_file.name,
    }


def test_dump_refuses_to_write_inside_the_source_folder(tmp_path):
    source = tmp_path / "hashes"
    source.mkdir()
    (source / ("c" * 32)).write_bytes(b"fixture")

    try:
        dump_hash_files_from_folder(source, source / "dump")
    except HashFileDumpError as exc:
        assert "outside the source folder" in str(exc)
    else:
        raise AssertionError("Expected output-inside-source folder to be rejected")
