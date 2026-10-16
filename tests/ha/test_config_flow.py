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
    with patch("custom_components.withings_local.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_KL: TEST_KL})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"address": ADDRESS, CONF_KL: TEST_KL}
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
    with patch(FETCH, return_value=(TEST_KL, {"1001": "Alice"})), patch("custom_components.withings_local.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], creds)
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
