"""Config flow: discover the scale over Bluetooth, then obtain its kl secret."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from .withings_wpp import account
from .withings_wpp.advertisement import WithingsUuid

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak, async_discovered_service_info
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS, CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .const import BODY_SMART_MODEL_ID, CONF_KL, DOMAIN, LOCAL_NAME_PREFIX

_LOGGER = logging.getLogger(__name__)


def is_body_smart(info: BluetoothServiceInfoBleak) -> bool:
    if info.name and info.name.startswith(LOCAL_NAME_PREFIX):
        return True
    return any((w := WithingsUuid.parse(u)) and w.model_id == BODY_SMART_MODEL_ID for u in info.service_uuids)


async def fetch_kl(hass, email: str, password: str, address: str) -> str:
    """Log in to the user's Withings account and return the scale's kl. Nothing is stored."""
    http = async_get_clientsession(hass)

    async def post(url: str, params: dict) -> dict:
        async with http.post(url, data=params, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    session = account.parse_login(await post(account.LOGIN_URL, account.login_params(email, password)))
    try:
        scales = account.parse_scales(await post(account.ASSOCIATION_URL, account.association_params(session)))
    finally:
        try:
            await post(account.LOGIN_URL, account.logout_params(session))
        except (aiohttp.ClientError, TimeoutError):
            _LOGGER.debug("Withings logout failed", exc_info=True)
    if not scales:
        raise account.AccountError("no Body Smart on this account")
    # On Linux the Bluetooth address is the scale's MAC; prefer the matching association.
    return next((s.kl for s in scales if s.mac and format_mac(s.mac) == format_mac(address)), scales[0].kl)


class WithingsLocalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Withings Local."""

    VERSION = 1

    def __init__(self) -> None:
        self._address: str | None = None
        self._name: str | None = None
        self._discovered: dict[str, str] = {}

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> ConfigFlowResult:
        if not is_body_smart(discovery_info):
            return self.async_abort(reason="not_supported")
        await self.async_set_unique_id(format_mac(discovery_info.address))
        self._abort_if_unique_id_configured()
        self._address = discovery_info.address
        self._name = discovery_info.name or LOCAL_NAME_PREFIX
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return await self.async_step_key()
        self._set_confirm_only()
        return self.async_show_form(step_id="bluetooth_confirm", description_placeholders={"name": self._name})

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._address = user_input[CONF_ADDRESS]
            self._name = self._discovered[self._address]
            await self.async_set_unique_id(format_mac(self._address), raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return await self.async_step_key()

        current = self._async_current_ids(include_ignore=False)
        for info in async_discovered_service_info(self.hass, connectable=True):
            if format_mac(info.address) not in current and is_body_smart(info):
                self._discovered[info.address] = f"{info.name or LOCAL_NAME_PREFIX} ({info.address})"
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(self._discovered)})
        )

    async def async_step_key(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="key", menu_options=["login", "manual"])

    async def async_step_login(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                kl = await fetch_kl(self.hass, user_input[CONF_EMAIL], user_input[CONF_PASSWORD], self._address)
            except account.InvalidCredentials:
                errors["base"] = "invalid_auth"
            except account.AccountError:
                errors["base"] = "no_scale"
            except (aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error fetching the scale key")
                errors["base"] = "unknown"
            else:
                return self._create(kl)
        return self.async_show_form(
            step_id="login",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL)),
                    vol.Required(CONF_PASSWORD): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                }
            ),
            errors=errors,
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            kl = user_input[CONF_KL].strip()
            if len(kl) < 16:
                errors[CONF_KL] = "invalid_key"
            else:
                return self._create(kl)
        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({vol.Required(CONF_KL): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))}),
            errors=errors,
        )

    def _create(self, kl: str) -> ConfigFlowResult:
        assert self._address is not None
        return self.async_create_entry(title=self._name or LOCAL_NAME_PREFIX, data={CONF_ADDRESS: self._address, CONF_KL: kl})
