import struct

import pytest

from withings_wpp.codec import Message, Reassembler, Reader, Tlv, WppError, decode_message, pack_str
from withings_wpp.messages import Cmd, Obj, ProbeReply, describe, probe


def test_probe_encoding():
    raw = probe(app_version=0x01020304, os_version=34).encode()
    assert raw == bytes.fromhex(
        "01 0101 0010"  # version, PROBE, payload length 16
        " 012a 0006 01 01 01020304"  # AppProbe: os=1, app=1, version
        " 0928 0002 0022"  # AppProbeOsVersion: 34
    )


def test_roundtrip():
    msg = Message(Cmd.SYNC_OK | 0x4000, (Tlv(Obj.NULL, b""), Tlv(0x1234, b"\x00\xff")))
    decoded = decode_message(msg.encode())
    assert decoded == msg
    assert decoded.from_device and decoded.base_command == Cmd.SYNC_OK


def test_reassembler_handles_fragments_and_back_to_back_messages():
    a = Message(Cmd.PROBE, (Tlv(1, bytes(300)),)).encode()
    b = Message(Cmd.SYNC_OK).encode()
    stream = a + b
    r = Reassembler()
    out = []
    for i in range(0, len(stream), 182):
        out += r.feed(stream[i : i + 182])
    assert [m.command for m in out] == [Cmd.PROBE, Cmd.SYNC_OK]
    assert r.pending == 0


@pytest.mark.parametrize(
    "data",
    [b"\x01\x01", b"\x02\x01\x01\x00\x00", b"\x01\x01\x01\x00\x05\x00\x01\x00\x09"],
)
def test_malformed(data):
    with pytest.raises(WppError):
        decode_message(data)


def test_probe_reply_parse():
    # Synthetic values only; never real device identifiers.
    value = (
        struct.pack(">HH", 1, 2)
        + pack_str("Body Smart")
        + pack_str("00:11:22:33:44:55")
        + pack_str("0123456789abcdef")
        + struct.pack(">I", 7)
        + pack_str("MFG")
        + struct.pack(">III", 10, 20, 30)
    )
    reply = ProbeReply.parse(value)
    assert reply.name == "Body Smart" and reply.soft_version == 20 and reply.extra == b""


def test_reader_bounds():
    with pytest.raises(WppError):
        Reader(b"\x05ab").str_()


def test_describe_hides_values():
    text = describe(Message(Cmd.PROBE, (Tlv(Obj.PROBE_REPLY, b"secret-ish"),)))
    assert "secret" not in text and "PROBE_REPLY[10]" in text


def test_stored_measure_get_state():
    from withings_wpp.messages import MeasureAction, stored_measure

    assert stored_measure(MeasureAction.GET_STATE).encode() == bytes.fromhex("01 010f 0006 0114 0002 00 00")


def test_cmd_error_parse():
    from withings_wpp.messages import CmdError

    assert str(CmdError.parse(bytes.fromhex("0101 fffffffb"))) == "cmd 257: not authenticated"
