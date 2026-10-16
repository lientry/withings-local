"""Constants for the Withings Local integration."""

DOMAIN = "withings_local"
CONF_KL = "kl"

LOCAL_NAME_PREFIX = "Body Smart"
BODY_SMART_MODEL_ID = 0x0010
# Don't reconnect for the same burst of advertisements after a sync.
POLL_COOLDOWN_SECONDS = 30
