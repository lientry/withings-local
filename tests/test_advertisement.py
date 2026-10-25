from withings_wpp.advertisement import FD77, Fd77, WithingsUuid, is_withings


def test_withings_uuid():
    w = WithingsUuid.parse("00000020-5749-5448-0010-000000000000")
    assert (w.service, w.model_id, w.tail) == (0x20, 0x10, "000000000000")
    assert WithingsUuid.parse("0000180f-0000-1000-8000-00805f9b34fb") is None
    # Withings' newer service has no model in it (the "5448" isn't one).
    assert WithingsUuid.parse("00000000-0000-5749-5448-494e47530000") is None


def test_fd77_flags():
    # version 1, model 0x010; flags TLV (type 1, len 1) = installed | sync requested
    fd = Fd77.parse(bytes.fromhex("1010 11 03"))
    assert (fd.version, fd.model_id) == (1, 0x10)
    assert fd.installed and fd.sync_requested and not fd.wake_up
    assert fd.wants_connection


def test_is_withings():
    assert is_withings([], {FD77: b"\x10\x10"})
    assert not is_withings(["0000180f-0000-1000-8000-00805f9b34fb"], {})


def test_fd77_reported_beamo_advertisements():
    # Issue #1: setup mode carries the MAC in field 2 (synthetic here); installed sets flag bit 0.
    setup = Fd77.parse(bytes.fromhex("1047 1100 26aabbccddeeff"))
    assert (setup.model_id, setup.installed, setup.fields[2]) == (71, False, bytes.fromhex("aabbccddeeff"))
    installed = Fd77.parse(bytes.fromhex("1047 1101 3400112233"))
    assert installed.installed and not installed.sync_requested and not installed.wants_connection


def test_profile_for():
    from withings_wpp.devices import BEAMO, BODY_SMART, profile_for

    assert profile_for([], {}, "Body Smart 55") is BODY_SMART
    assert profile_for(["00000020-5749-5448-0010-001122334455"], {}) is BODY_SMART
    assert profile_for(["00000000-0000-5749-5448-494e47530000"], {FD77: bytes.fromhex("10471101")}) is BEAMO
    assert profile_for(["00000000-0000-5749-5448-494e47530000"], {}) is None  # no model to go on
    assert profile_for([], {FD77: bytes.fromhex("10931101")}) is None  # another Withings model
