# Changelog

Notable changes to the Withings Local integration. Versions follow [semantic versioning](https://semver.org); each one is a GitHub release that HACS offers as an update.

## [Unreleased]

## [0.2.0] - 2026-10-16

### Added
- **One device per Withings user** with that person's latest weigh-in. Names come from the Withings account when you set up with your login; otherwise users show as "User 1", "User 2" (rename them in Home Assistant).
- **Guest weigh-ins** get their own device, with weight only.
- **Battery level** sensor on the scale's device.
- **Diagnostics download**, with the key, address and user names removed.
- **Debug logging** of every advertisement and sync, to troubleshoot Bluetooth reachability.
- **Integration icon.**

### Changed
- Weigh-ins are de-duplicated by time and measurement type, since the scale re-sends its whole store on every sync.
- Sessions end with `SYNC_OK`, as the scale expects. Verified to delete nothing: the Withings app still receives the same readings.
- A weigh-in is also detected from the manufacturer data, so adapters and proxies that scan passively work too.

### Fixed
- User IDs in stored records are read correctly; only the valid ones are used.
- On the login and manual-key steps, submitting empty fields goes back to the choice of key method.

### Upgrade notes
- The single-user sensors from 0.1.0 are removed automatically. New per-user sensors appear after the next weigh-in.

## [0.1.0] - 2026-10-16

### Added
- First version: Bluetooth discovery of the Body Smart (WBS13), key setup (Withings login or pasted `kl`), and sensors for the latest weigh-in.
