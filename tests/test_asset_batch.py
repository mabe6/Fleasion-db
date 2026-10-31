from __future__ import annotations

import json

from fleasion.proxy.addons.texture_stripper import TextureStripper
from fleasion.proxy.asset_batch import (
    from_v1,
    is_batch_request,
    is_v3_request,
    to_v1,
    unwrap_response,
)

V3_BODY = json.dumps(
    {
        'assets': [
            {'requestId': '0', 'assetId': 111, 'extra': 'keep'},
            {'requestId': '1', 'asset': {'hash': 'abc'}},
            {'requestId': '2', 'assetId': 222},
        ]
    }
).encode()


def test_paths() -> None:
    assert is_batch_request(b'POST /v1/assets/batch HTTP/1.1')
    assert is_batch_request(b'POST /v3/assets/batch HTTP/1.1')
    assert not is_batch_request(b'GET /v1/asset/?id=1 HTTP/1.1')
    assert is_v3_request(b'POST /v3/assets/batch HTTP/1.1')
    assert not is_v3_request(b'POST /v1/assets/batch HTTP/1.1')


def test_flatten_and_roundtrip_unchanged() -> None:
    converted = to_v1(V3_BODY)
    assert converted is not None
    flat_body, batch = converted
    flat = json.loads(flat_body)
    assert isinstance(flat, list) and len(flat) == 3
    assert flat[1] == {'requestId': '1', 'asset': {'hash': 'abc'}}
    assert json.loads(from_v1(flat_body, batch)) == json.loads(V3_BODY)


def test_addon_replacement_and_removal_survive() -> None:
    converted = to_v1(V3_BODY)
    assert converted is not None
    flat_body, batch = converted
    flat = json.loads(flat_body)
    flat[0]['assetId'] = 999
    del flat[2]
    rebuilt = json.loads(from_v1(json.dumps(flat).encode(), batch))
    assert rebuilt['assets'] == [
        {'requestId': '0', 'assetId': 999, 'extra': 'keep'},
        {'requestId': '1', 'asset': {'hash': 'abc'}},
    ]


def test_missing_request_id_is_not_leaked() -> None:
    body = json.dumps({'assets': [{'assetId': 5}], 'other': 1}).encode()
    converted = to_v1(body)
    assert converted is not None
    flat_body, batch = converted
    assert json.loads(from_v1(flat_body, batch)) == {'assets': [{'assetId': 5}], 'other': 1}


def test_unrecognised_bodies_pass_through() -> None:
    assert to_v1(b'not json') is None
    assert to_v1(b'[]') is None
    assert to_v1(b'{"assets": 1}') is None
    assert to_v1(b'{"assets": [{"requestId": "a"}, {"requestId": "a"}]}') is None


def test_v3_body_through_real_stripper() -> None:
    TextureStripper.reset_routes()

    class _Config:
        def get_all_replacements(self):  # noqa: ANN202
            return {}, set(), {}, {}

    flat_body, batch = to_v1(V3_BODY)  # type: ignore[misc]
    modified, _ = TextureStripper(_Config()).process_batch_request(
        flat_body, {}, ({111: 999}, {222}, {}, {}), 'batch'
    )
    rebuilt = json.loads(from_v1(modified, batch))
    # 111 replaced, 222 removed, hash-only item and extra keys untouched
    assert rebuilt['assets'] == [
        {'requestId': '0', 'assetId': 999, 'extra': 'keep'},
        {'requestId': '1', 'asset': {'hash': 'abc'}},
    ]


def test_unwrap_response() -> None:
    assert json.loads(unwrap_response(b'{"assets":[{"requestId":"0"}]}')) == [{'requestId': '0'}]
    assert unwrap_response(b'[{"requestId":"0"}]') == b'[{"requestId":"0"}]'
    assert json.loads(unwrap_response(b'{"items":[1]}')) == [1]
    assert unwrap_response(b'nope') == b'nope'
