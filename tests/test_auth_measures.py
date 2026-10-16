import hashlib
import struct

from withings_wpp.auth import answer, challenge_reply, verify
from withings_wpp.codec import Message, Tlv, decode_message
from withings_wpp.measures import parse_groups
from withings_wpp.messages import Cmd, Obj

# Synthetic test values only.
MAC = "00:11:22:33:44:55"
KL = "test-kl-not-a-real-secret-000000"


def test_answer_matches_formula():
    ch = bytes(range(16))
    assert answer(ch, MAC, KL) == hashlib.sha1(ch + MAC.encode() + KL.encode()).digest()


def test_challenge_reply_layout_and_verify():
    own = b"\xaa" * 16
    msg = decode_message(challenge_reply(bytes(16), MAC, KL, own).encode())
    assert msg.command == Cmd.PROBE_CHALLENGE
    resp, chal = msg.tlvs
    assert resp.type == Obj.PROBE_CHALLENGE_RESPONSE and resp.value[0] == 20
    assert chal.type == Obj.PROBE_CHALLENGE and chal.value == bytes([17]) + MAC.encode() + bytes([16]) + own
    assert verify(answer(own, MAC, KL), own, MAC, KL)
    assert not verify(b"\x00" * 20, own, MAC, KL)


def _meta(uid, users, attrib, t, prefixed=False):
    body = struct.pack(">IB", uid, len(users))
    if prefixed:
        body += bytes([len(users)])
    return body + b"".join(struct.pack(">I", u) for u in users) + struct.pack(">BI", attrib, t)


def _data(raw, mtype, exp):
    return struct.pack(">iHh", raw, mtype, exp)


def test_parse_groups_both_meta_layouts():
    for prefixed in (False, True):
        msgs = [
            Message(Cmd.STORED_MEASURE, (Tlv(Obj.STORED_MEASURE_META, _meta(7, [42], 0, 1_700_000_000, prefixed)),
                                         Tlv(Obj.STORED_MEASURE_DATA, _data(72345, 1, -3)),
                                         Tlv(Obj.STORED_MEASURE_DATA, _data(215, 6, -1)))),
            Message(Cmd.STORED_MEASURE, (Tlv(Obj.NULL, b""),)),
        ]
        (g,) = parse_groups(msgs)
        assert g.user_ids == [42] and g.time.timestamp() == 1_700_000_000
        assert g.value("weight") == 72.345 and g.value("fat_ratio") == 21.5
