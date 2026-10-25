from unittest.mock import patch

from custom_components.withings_local.withings_wpp import account

from homeassistant.config_entries import SOURCE_BLUETOOTH
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.withings_local.const import CONF_KL, DOMAIN

from .conftest import ADDRESS, TEST_KL, service_info

FETCH = "custom_components.withings_local.config_flow.fetch_kl"


async def _to_key_menu(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info())
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "bluetooth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.MENU and result["step_id"] == "key"
    return result


async def test_bluetooth_discovery_manual_key(hass: HomeAssistant, mock_bluetooth) -> None:
    result = await _to_key_menu(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "manual"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_KL: "short"})
    assert result["errors"] == {CONF_KL: "invalid_key"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_KL: TEST_KL})
    assert result["type"] is FlowResultType.MENU and result["step_id"] == "pair"
    with patch("custom_components.withings_local.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "pair_skip"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"address": ADDRESS, CONF_KL: TEST_KL, "model": 16}
    assert result["result"].unique_id == ADDRESS.lower()


async def test_bluetooth_discovery_login(hass: HomeAssistant, mock_bluetooth) -> None:
    result = await _to_key_menu(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "login"})
    creds = {"email": "user@example.com", "password": "pw"}
    with patch(FETCH, side_effect=account.InvalidCredentials("bad", 100)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], creds)
    assert result["errors"] == {"base": "invalid_auth"}
    with patch(FETCH, side_effect=account.AccountError("none")):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], creds)
    assert result["errors"] == {"base": "no_scale"}
    with patch(FETCH, return_value=(TEST_KL, {"1001": "Alice"})):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], creds)
    assert result["step_id"] == "pair"
    with patch("custom_components.withings_local.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "pair_skip"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_KL] == TEST_KL
    assert result["data"]["users"] == {"1001": "Alice"}
    assert "email" not in result["data"] and "password" not in result["data"]


async def test_discovery_of_other_device_aborts(hass: HomeAssistant, mock_bluetooth) -> None:
    info = service_info(name="Something else", uuid="0000180f-0000-1000-8000-00805f9b34fb")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=info)
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "not_supported"


async def test_empty_submit_goes_back_to_key_options(hass: HomeAssistant, mock_bluetooth) -> None:
    result = await _to_key_menu(hass)
    # Manual key -> empty submit -> back to the menu.
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "manual"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.MENU and result["step_id"] == "key"
    # Login -> half-filled is an error, empty goes back.
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "login"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"email": "user@example.com"})
    assert result["errors"] == {"base": "missing_credentials"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.MENU and result["step_id"] == "key"


async def test_unnamed_advertisement_gets_readable_title(hass: HomeAssistant, mock_bluetooth) -> None:
    # Passive scanners may not receive the local name; HA then reports the address as the name.
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=service_info(name=ADDRESS)
    )
    assert result["description_placeholders"] == {"name": "Body Smart"}



class FakeSession:
    def __init__(self, accept=True, already_paired=False, start_error=None):
        self.accept, self.already, self.code, self.closed = accept, already_paired, None, False
        self.start_error = start_error

    async def start(self):
        if self.start_error is not None:
            raise self.start_error
        return self.already

    async def wait_for_passkey_request(self):
        return None

    async def submit_passkey(self, code):
        from custom_components.withings_local.pairing import PairingFailed

        self.code = code
        if not self.accept:
            raise PairingFailed("wrong code")

    async def close(self):
        self.closed = True


async def _to_pair_menu(hass):
    result = await _to_key_menu(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "manual"})
    return await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_KL: TEST_KL})


def _pairing_patches(session=None, never_advertise=False, path_error=None):
    from .conftest import SETUP_UUID

    def fake_register(hass, callback, address):
        """Like HA's every-advertisement callback: fires for unchanged data too."""
        if not never_advertise:
            weigh_in = service_info()
            weigh_in.time = 1e12
            setup = service_info(uuid=SETUP_UUID, mfr=b"\x00\x00\x00\x00")
            setup.time = 1e12
            hass.loop.call_soon(callback, weigh_in)  # ignored: not setup mode
            hass.loop.call_soon(callback, setup)  # accepted
        return lambda: None

    path = patch(
        "custom_components.withings_local.config_flow.device_path",
        side_effect=path_error,
        return_value="/org/bluez/hci0/dev_00_11_22_33_44_55",
    )
    return (
        patch("custom_components.withings_local.config_flow.bluetooth.async_register_advertisement_callback", fake_register),
        path,
        patch("custom_components.withings_local.config_flow.PairingSession", return_value=session or FakeSession()),
    )


async def _run_pair_now(hass, result, patches):
    with patches[0], patches[1], patches[2]:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "pair_now"})
        if result["type"] is FlowResultType.SHOW_PROGRESS:
            await hass.async_block_till_done()
            result = await hass.config_entries.flow.async_configure(result["flow_id"])
    return result


async def test_pairing_with_code_creates_entry(hass: HomeAssistant, mock_bluetooth) -> None:
    session = FakeSession()
    result = await _run_pair_now(hass, await _to_pair_menu(hass), _pairing_patches(session))
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "passkey"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"passkey": "12345"})
    assert result["errors"] == {"passkey": "invalid_passkey"}
    with patch("custom_components.withings_local.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"passkey": "123456"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert session.code == 123456 and session.closed


async def test_already_paired_skips_code(hass: HomeAssistant, mock_bluetooth) -> None:
    session = FakeSession(already_paired=True)
    with patch("custom_components.withings_local.async_setup_entry", return_value=True):
        result = await _run_pair_now(hass, await _to_pair_menu(hass), _pairing_patches(session))
        if result["type"] is not FlowResultType.CREATE_ENTRY:
            result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.CREATE_ENTRY and session.closed


async def test_wrong_code_offers_retry(hass: HomeAssistant, mock_bluetooth) -> None:
    result = await _run_pair_now(hass, await _to_pair_menu(hass), _pairing_patches(FakeSession(accept=False)))
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"passkey": "000000"})
    assert result["type"] is FlowResultType.MENU and result["step_id"] == "pair_failed"


async def test_unexpected_pairing_error_offers_retry(hass: HomeAssistant, mock_bluetooth) -> None:
    # e.g. no system D-Bus: not a PairingFailed, but the user still gets the retry menu, not "unknown error".
    session = FakeSession(start_error=OSError("no system bus"))
    result = await _run_pair_now(hass, await _to_pair_menu(hass), _pairing_patches(session))
    assert result["type"] is FlowResultType.MENU and result["step_id"] == "pair_failed"
    assert "no system bus" in result["description_placeholders"]["error"] and session.closed


async def test_scale_not_in_setup_mode_times_out(hass: HomeAssistant, mock_bluetooth) -> None:
    with patch("custom_components.withings_local.config_flow.PAIRING_ADVERTISEMENT_TIMEOUT", 0.05):
        result = await _run_pair_now(hass, await _to_pair_menu(hass), _pairing_patches(never_advertise=True))
    assert result["type"] is FlowResultType.MENU and result["step_id"] == "pair_timeout"


async def test_unsupported_adapter_continues_without_pairing(hass: HomeAssistant, mock_bluetooth) -> None:
    from custom_components.withings_local.pairing import PairingUnsupported

    patches = _pairing_patches(path_error=PairingUnsupported("pairing_remote_adapter"))
    result = await _run_pair_now(hass, await _to_pair_menu(hass), patches)
    assert result["type"] is FlowResultType.MENU and result["step_id"] == "pair_unsupported"
    with patch("custom_components.withings_local.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "pair_skip"})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def _entry(hass):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS.lower(), title="Body Smart",
                            data={"address": ADDRESS, CONF_KL: TEST_KL})
    entry.add_to_hass(hass)
    return entry


async def test_reconfigure_pairs_again(hass: HomeAssistant, mock_bluetooth) -> None:
    entry = await _entry(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.MENU and result["step_id"] == "pair"
    result = await _run_pair_now(hass, result, _pairing_patches())
    with patch("custom_components.withings_local.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"passkey": "654321"})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reconfigure_successful"


async def test_reauth_pairs_again(hass: HomeAssistant, mock_bluetooth) -> None:
    entry = await _entry(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.MENU and result["step_id"] == "pair"
    result = await _run_pair_now(hass, result, _pairing_patches())
    with patch("custom_components.withings_local.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"passkey": "654321"})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reauth_successful"


async def test_beamo_discovery_creates_beamo_entry(hass: HomeAssistant, mock_bluetooth) -> None:
    from .conftest import beamo_info

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=beamo_info())
    assert result["step_id"] == "bluetooth_confirm" and result["description_placeholders"] == {"name": "BeamO"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "login"})
    with patch(FETCH, return_value=(TEST_KL, {})) as fetch:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"email": "user@example.com", "password": "pw"})
    assert fetch.call_args.args[-1] == 71  # the BeamO's key, not a scale's
    assert result["step_id"] == "pair" and "temperature measurement" in result["description_placeholders"]["wake_up"]
    with patch("custom_components.withings_local.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "pair_skip"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "BeamO" and result["data"]["model"] == 71


async def test_beamo_pairs_on_any_advertisement(hass: HomeAssistant, mock_bluetooth) -> None:
    """Not only in setup mode: that's the QR code the Withings app adds it to an account with."""
    from .conftest import BEAMO_INSTALLED, beamo_info

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_BLUETOOTH}, data=beamo_info())
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "manual"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_KL: TEST_KL})

    def fake_register(hass, callback, address):
        info = beamo_info(BEAMO_INSTALLED)
        info.time = 1e12
        hass.loop.call_soon(callback, info)
        return lambda: None

    session = FakeSession()
    patches = _pairing_patches(session)
    patches = (patch("custom_components.withings_local.config_flow.bluetooth.async_register_advertisement_callback", fake_register), *patches[1:])
    result = await _run_pair_now(hass, result, patches)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "passkey"
