"""Constants for the Withings Local integration."""

DOMAIN = "withings_local"
CONF_KL = "kl"
CONF_MODEL = "model"  # Withings model ID; entries from before 0.4 have none and are Body Smart
CONF_USERS = "users"  # {user id (str): first name}, from the Withings account when known
OPT_KNOWN_USERS = "known_users"  # user ids seen on the scale, in order of first appearance
GUEST_USER_ID = 0

# Don't reconnect for the same burst of advertisements after a sync.
POLL_COOLDOWN_SECONDS = 30
# A BeamO advertising without asking for a sync may still hold a reading: whether it sets the
# sync-requested flag is unconfirmed. Look at most this often.
IDLE_POLL_SECONDS = 300
# A full read takes ~1-3 s; anything far longer is a stuck link.
SESSION_TIMEOUT_SECONDS = 45
