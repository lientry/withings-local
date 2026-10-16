"""Mutual challenge authentication.

Each side proves it knows `kl` by answering SHA1(challenge ‖ mac ‖ kl), where `mac` is the MAC
string exactly as the scale sent it in PROBE_CHALLENGE and `kl` is the per-scale secret.
"""

from __future__ import annotations

import hashlib
import hmac
import os

from .codec import Message, Tlv, pack_str
from .messages import Cmd, Obj

CHALLENGE_LEN = 16


def answer(challenge: bytes, mac: str, kl: str) -> bytes:
    return hashlib.sha1(challenge + mac.encode() + kl.encode()).digest()


def new_challenge() -> bytes:
    return os.urandom(CHALLENGE_LEN)


def challenge_reply(device_challenge: bytes, mac: str, kl: str, own_challenge: bytes) -> Message:
    """Answer the scale's challenge and send it one of our own."""
    return Message(
        Cmd.PROBE_CHALLENGE,
        (
            Tlv(Obj.PROBE_CHALLENGE_RESPONSE, pack_str(answer(device_challenge, mac, kl))),
            Tlv(Obj.PROBE_CHALLENGE, pack_str(mac) + pack_str(own_challenge)),
        ),
    )


def verify(device_answer: bytes, own_challenge: bytes, mac: str, kl: str) -> bool:
    return hmac.compare_digest(device_answer, answer(own_challenge, mac, kl))
