"""Translate Roblox v3 asset batch bodies to and from the v1 shape the addons expect.

Current Roblox clients POST ``{"assets": [...]}`` to ``/v3/assets/batch``.  The
addons (TextureStripper, CacheScraper) only understand the v1 body, a bare JSON
list of items.  ``to_v1`` flattens a v3 request so the addons can run unchanged,
``from_v1`` rebuilds the v3 request from whatever the addons returned, and
``unwrap_response`` flattens the v3 response for the response hooks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

V1_BATCH_PATH = b'/v1/assets/batch'
V3_BATCH_PATH = b'/v3/assets/batch'
EMPTY_V3_RESPONSE = b'{"assets":[]}'


@dataclass(frozen=True)
class V3Batch:
    """Original v3 request pieces needed to rebuild the request after the addons ran.

    Attributes
    ----------
    envelope
        Top-level request object, kept so unknown keys survive the round trip.
    items
        Original v3 items keyed by ``requestId``.
    synthetic
        Keys that were invented because the item had no ``requestId``.
    """

    envelope: dict[str, Any]
    items: dict[str, dict[str, Any]]
    synthetic: frozenset[str]


def is_batch_request(request_line: bytes) -> bool:
    """Return whether an HTTP request line targets the v1 or v3 batch endpoint."""
    return V1_BATCH_PATH in request_line or V3_BATCH_PATH in request_line


def is_v3_request(request_line: bytes) -> bool:
    """Return whether an HTTP request line targets the v3 batch endpoint."""
    return V3_BATCH_PATH in request_line


def to_v1(body: bytes) -> tuple[bytes, V3Batch] | None:
    """Flatten a v3 batch request into a v1 list body.

    Returns ``None`` when the body is not a recognisable v3 batch, so the caller
    can forward it untouched instead of guessing.
    """
    try:
        data = json.loads(body)
    except ValueError:
        return None
    assets = data.get('assets') if isinstance(data, dict) else None
    if not isinstance(assets, list):
        return None

    items: dict[str, dict[str, Any]] = {}
    synthetic: set[str] = set()
    flat: list[dict[str, Any]] = []
    for index, item in enumerate(assets):
        if not isinstance(item, dict):
            return None
        key = str(item['requestId']) if 'requestId' in item else f'idx{index}'
        if key in items:
            # Duplicate ids cannot be matched back reliably
            return None
        flat_item = dict(item)
        if 'requestId' not in item:
            flat_item['requestId'] = key
            synthetic.add(key)
        items[key] = item
        flat.append(flat_item)

    envelope = {k: v for k, v in data.items() if k != 'assets'}
    return json.dumps(flat, separators=(',', ':')).encode(), V3Batch(
        envelope, items, frozenset(synthetic)
    )


def from_v1(body: bytes, batch: V3Batch) -> bytes:
    """Rebuild a v3 request body from the (possibly modified) v1 list."""
    flat = json.loads(body)
    assets: list[Any] = []
    for item in flat:
        if not isinstance(item, dict):
            assets.append(item)
            continue
        key = str(item.get('requestId', ''))
        original = batch.items.get(key)
        # Addon changes win, untouched v3-only keys are kept from the original
        merged = {**original, **item} if original is not None else dict(item)
        if key in batch.synthetic:
            merged.pop('requestId', None)
        assets.append(merged)
    return json.dumps({**batch.envelope, 'assets': assets}, separators=(',', ':')).encode()


def unwrap_response(body: bytes) -> bytes:
    """Flatten a v3 batch response to the v1 list the response hooks read."""
    try:
        data = json.loads(body)
    except ValueError:
        return body
    if isinstance(data, list):
        return body
    if isinstance(data, dict):
        assets = data.get('assets')
        if not isinstance(assets, list):
            # Fall back to the first list value in case the key is named differently
            assets = next((v for v in data.values() if isinstance(v, list)), None)
        if isinstance(assets, list):
            return json.dumps(assets, separators=(',', ':')).encode()
    return body
