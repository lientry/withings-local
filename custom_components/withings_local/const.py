"""Constants for the Withings Local integration."""

DOMAIN = "withings_local"
CONF_KL = "kl"
CONF_USERS = "users"  # {user id (str): first name}, from the Withings account when known
OPT_KNOWN_USERS = "known_users"  # user ids seen on the scale, in order of first appearance
GUEST_USER_ID = 0

LOCAL_NAME_PREFIX = "Body Smart"
BODY_SMART_MODEL_ID = 0x0010
# Don't reconnect for the same burst of advertisements after a sync.
POLL_COOLDOWN_SECONDS = 30
