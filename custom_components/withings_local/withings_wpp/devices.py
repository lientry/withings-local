"""What differs between supported Withings devices: where WPP runs and how a session behaves.

The codec, authentication and stored-measurement commands are the same on every device; a
profile only records the differences. The BeamO profile comes from a community report
(issue #1, one BeamO C8 on macOS) and hasn't been tested with Home Assistant yet.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .advertisement import FD77, Fd77, WithingsUuid
from .codec import Message
from .messages import beamo_probe, probe


@dataclass(frozen=True)
class DeviceProfile:
    model_id: int
    name: str
    # Model name in the device registry, when known.
    model_code: str | None
    # Matches the WPP characteristic UUID (lower case).
    is_wpp_characteristic: Callable[[str], bool]
    probe: Callable[[], Message]
    # The device answers our PROBE with a challenge, never with a PROBE (no unauthenticated sessions).
    always_challenges: bool
    # Send SYNC_OK after a read and echo the device's own. Off where its effect is unknown.
    sync_ok: bool
    # Wait this long after subscribing, so messages the device pushes on its own arrive (and are
    # dropped) before the first request.
    settle_seconds: float = 0.0


BODY_SMART = DeviceProfile(
    model_id=0x0010,
    name="Body Smart",
    model_code="WBS13",
    is_wpp_characteristic=lambda uuid: uuid.startswith("00000024") and "-5749-5448-" in uuid,
    probe=probe,
    always_challenges=False,
    sync_ok=True,
)

BEAMO = DeviceProfile(
    model_id=0x0047,
    name="BeamO",
    model_code=None,
    # Withings' newer service 00000000-0000-5749-5448-494e47530000; `…0005` doesn't answer.
    is_wpp_characteristic=lambda uuid: uuid == "00000004-0000-5749-5448-494e47530000",
    probe=beamo_probe,
    always_challenges=True,
    # Reported: the app uploads, then deletes the records; SYNC_OK's effect is unknown. Never send it.
    sync_ok=False,
    settle_seconds=1.0,
)

PROFILES = {p.model_id: p for p in (BODY_SMART, BEAMO)}


def model_ids(service_uuids, service_data: dict) -> set[int]:
    """Withings model IDs in an advertisement: from the "WITH" service UUID and the FD77 data."""
    ids = {w.model_id for u in service_uuids if (w := WithingsUuid.parse(u))}
    for key, value in service_data.items():
        if key.lower() == FD77 and (fd := Fd77.parse(bytes(value))):
            ids.add(fd.model_id)
    return ids


def profile_for(service_uuids, service_data: dict, name: str | None = None) -> DeviceProfile | None:
    """The supported device this advertisement comes from, if any."""
    if name and name.startswith(BODY_SMART.name):
        return BODY_SMART
    return next((PROFILES[m] for m in sorted(model_ids(service_uuids, service_data)) if m in PROFILES), None)
