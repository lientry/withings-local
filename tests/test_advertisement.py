from withings_wpp.advertisement import FD77, Fd77, WithingsUuid, is_withings


def test_withings_uuid():
    w = WithingsUuid.parse("00000020-5749-5448-0010-000000000000")
    assert (w.service, w.model_id, w.tail) == (0x20, 0x10, "000000000000")
    assert WithingsUuid.parse("0000180f-0000-1000-8000-00805f9b34fb") is None


def test_fd77_flags():
    # version 1, model 0x010; flags TLV (type 1, len 1) = installed | sync requested
    fd = Fd77.parse(bytes.fromhex("1010 11 03"))
    assert (fd.version, fd.model_id) == (1, 0x10)
    assert fd.installed and fd.sync_requested and not fd.wake_up
    assert fd.wants_connection


def test_is_withings():
    assert is_withings([], {FD77: b"\x10\x10"})
    assert not is_withings(["0000180f-0000-1000-8000-00805f9b34fb"], {})
