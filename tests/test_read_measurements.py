"""Exercise the CLI without Bluetooth hardware or real credentials."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tools import read_measurements as cli
from withings_wpp.devices import BEAMO, BODY_SMART


@pytest.mark.parametrize("profile", [BODY_SMART, BEAMO])
@pytest.mark.parametrize("reason_timeout", [False, True])
async def test_cli_reads_records_even_if_connect_reason_times_out(
    tmp_path, monkeypatch, capsys, profile, reason_timeout
):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    (secrets / "scale.json").write_text(json.dumps({"model": profile.model_id, "kl": "synthetic-test-key-only"}))
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    device = SimpleNamespace(address="00:11:22:33:44:55")

    class Scanner:
        def __init__(self, callback):
            self.callback = callback

        async def __aenter__(self):
            self.callback(device, SimpleNamespace(service_uuids=[], service_data={}, local_name=None))
            return self

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(cli, "BleakScanner", Scanner)
    monkeypatch.setattr(cli, "profile_for", lambda *args: profile)
    transport = MagicMock()
    transport.__aenter__.return_value = transport
    monkeypatch.setattr(cli, "BleakClient", MagicMock(return_value=transport))
    session = SimpleNamespace(start=AsyncMock(), sync_ok=profile is BODY_SMART)
    session_factory = MagicMock(return_value=session)
    monkeypatch.setattr(cli, "WppSession", session_factory)
    group = SimpleNamespace(
        time=datetime(2026, 10, 25, tzinfo=UTC),
        measures=[SimpleNamespace(name="body_temperature", value=36.7, unit="C")],
        unknown_tlvs=[],
    )
    client = SimpleNamespace(
        authenticate=AsyncMock(return_value=SimpleNamespace(authenticated=True, scale_verified=True)),
        connect_reason=AsyncMock(return_value=2, side_effect=TimeoutError if reason_timeout else None),
        measure_status=AsyncMock(return_value=SimpleNamespace(count=1)),
        measures=AsyncMock(return_value=[group]),
        sync_ok=AsyncMock(),
        disconnect=AsyncMock(),
    )
    monkeypatch.setattr(cli, "ScaleClient", lambda session: client)
    monkeypatch.setattr(cli, "merge_by_time", lambda groups: groups)

    await cli.main()

    assert session_factory.call_args.kwargs["profile"] is profile
    client.measure_status.assert_awaited_once()
    client.measures.assert_awaited_once()
    client.disconnect.assert_awaited_once()
    assert client.sync_ok.await_count == (1 if profile is BODY_SMART else 0)
    output = capsys.readouterr().out
    assert "body_temperature=36.7 C" in output
    if reason_timeout:
        assert "connect reason timed out" in output
