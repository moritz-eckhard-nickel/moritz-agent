# SPDX-License-Identifier: LicenseRef-MSOL-1.1
from __future__ import annotations

import random

import pytest

from moritz_agent.phone.sip import (
    AudioPort,
    backoff_delay,
    ip_allowed,
    parse_source_ip,
    ring_duration,
)


@pytest.mark.parametrize(
    ("address", "ip"),
    [
        ("192.168.1.176:5060", "192.168.1.176"),
        ("[::1]:5060", "::1"),
        ("10.0.0.5", "10.0.0.5"),
        ("fe80::1", "fe80::1"),
    ],
)
def test_parse_source_ip(address, ip):
    assert parse_source_ip(address) == ip


def test_acl_accepts_single_addresses_and_networks():
    allowed = ["192.168.1.176", "10.1.0.0/16"]
    assert ip_allowed("192.168.1.176", allowed)
    assert ip_allowed("10.1.200.3", allowed)
    assert not ip_allowed("192.168.1.177", allowed)
    assert not ip_allowed("10.2.0.1", allowed)


def test_acl_empty_list_allows_nobody_and_garbage_is_rejected():
    assert not ip_allowed("192.168.1.176", [])
    assert not ip_allowed("not-an-ip", ["192.168.1.176"])
    assert not ip_allowed("192.168.1.176", ["garbage"])


def test_backoff_doubles_and_is_capped():
    assert [backoff_delay(n, 5, 60) for n in range(6)] == [5, 10, 20, 40, 60, 60]


def test_audio_port_pads_with_silence_and_tracks_backlog():
    port = AudioPort()
    assert port.take(640) == bytes(640)  # nothing queued: steady silence keeps RTP flowing
    port.enqueue(b"\x01\x00" * 480)  # 30 ms
    assert port.pending_ms() == 30
    assert port.take(640) == b"\x01\x00" * 320
    assert port.take(640) == b"\x01\x00" * 160 + bytes(320)
    assert port.pending_ms() == 0
    port.enqueue(b"\x01\x00" * 100)
    port.clear()
    assert port.pending_ms() == 0


def test_ring_duration_stays_within_the_limits_and_varies():
    rng = random.Random(7)
    values = [ring_duration(4.0, 8.0, rng) for _ in range(200)]
    assert all(4.0 <= value <= 8.0 for value in values)
    assert max(values) - min(values) > 2.0  # really random, not a constant


def test_ring_duration_edge_cases():
    assert ring_duration(0, 0) == 0
    assert ring_duration(5.0, 5.0) == 5.0
    assert 4.0 <= ring_duration(8.0, 4.0) <= 8.0  # swapped limits are tolerated
    assert ring_duration(-3.0, 0.0) == 0.0  # never negative
