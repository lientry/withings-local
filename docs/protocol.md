# WPP protocol notes (Body Smart)

These notes are written in our own words and come from two sources: public interoperability notes and our own observations of our scale. Each item is marked:
- **observed**: seen on our scale
- **reported**: from public notes, not yet confirmed on our scale

## Transport — observed
- The scale advertises for about 15 s after a short press of the button underneath it. In Wi-Fi mode it did not advertise when idle or after a weigh-in.
- It has one GATT service `00000020-5749-5448-0010-000000000000` with one characteristic `00000024-5749-5448-0010-000000000000` (notify, write, write-without-response).
  - Requests are written to the characteristic and responses come back as notifications on it.
- The ATT MTU is 185. A 59-byte probe reply arrived in one notification.
- **No link encryption was required** for subscribing, writing a PROBE, or receiving the reply. This differs from reports about the Body+, which rejects writes until the link is encrypted.

## Framing — observed (probe exchange)
```
message = 0x01 | command:u16 BE | length:u16 BE | TLV*
TLV     = type:u16 BE | length:u16 BE | value
```
- Strings inside TLV values have a 1-byte length prefix.
- **reported:** command bit `0x4000` marks a request initiated by the device. A list ends with a TLV of type 256 and length 0.

## PROBE (command 257) — observed
**Request:**
- `APP_PROBE` (298): `os:u8, app:u8, version:u32`. We sent os=1, app=1, version=1, which the scale accepted.
- `APP_PROBE_OS_VERSION` (2344): `u16`. We sent 34.

**Reply in setup mode** (session started by a button press) — command 257 with:
- `PROBE_REPLY` (257), 59 bytes:
  - `vid:u16, pid:u16`
  - `name:str`, which was "Body Smart"
  - `mac:str`, 17 characters (`aa:bb:…`)
  - `secret:str`, which was empty on our scale
  - `hard_version:u32`, which was 0xFFFFFF
  - `mfg_id:str`, 8 characters
  - `bootloader:u32` (2), `firmware:u32` (1311), `rescue:u32` (0xFFFFFF)

  The layout parsed exactly, with no bytes left over.
- `FACTORY_STATE` (300), 1 byte, value `00`. Meaning not confirmed; probably "already set up".

The session stayed connected afterwards with no device-initiated requests during the 8 s listen.

## Session flow used by the phone app — from app analysis, not yet run by us
Each item is marked **app** (seen in the decompiled app's behaviour) or **reported** (from public notes).

1. **Transport.** The app requests an MTU, bonds if not bonded, then enables notifications. Its own messages over 200 bytes are split at TLV boundaries into several messages with the same command. Multi-message replies end with a Null TLV (256).
2. **PROBE** (257) with `APP_PROBE` (os=1, app=1, version 202609240) and `APP_PROBE_OS_VERSION` (Android API level). The scale answers in one of two ways:
   - cmd 257 + `PROBE_REPLY`: setup mode, no authentication (what we observed after a button press);
   - cmd 296 + `PROBE_CHALLENGE` (290): `mac:str`, `challenge:bytes` (16).
3. **Challenge** (app). Answer = `SHA1(challenge ‖ mac ‖ kl)`, 20 raw bytes, where `mac` is the exact string the scale sent and `kl` the per-scale secret as a string.
   - The app sends cmd 296 with `PROBE_CHALLENGE_RESPONSE` (291) plus its own `PROBE_CHALLENGE` (16 random bytes).
   - The scale proves itself the same way in a cmd-257 reply.
   - Requests from the scale before authentication are answered with error −5 (not authenticated).
4. **CONNECT_REASON** (cmd 273, no payload). The reply holds `CONNECT_REASON` (280): `reason:u16`.
   - Values: 1 = button, 2 = weigh-in, 3 = firmware update, …
   - The app only runs a measurement sync when the reason is 2 (weigh-in).
5. **Init steps** the app runs before reading. Several of these **write state** to the scale, and we must not copy them blindly:
   - server session upload (269)
   - `TIME_SET` (1281): `utc:u32, gmt_offset:s32, dst_change:u32, next_gmt_offset:s32`; reply `TIME_SET_REPLY` (1282): `drift:s32`
   - re-sending the association keys (308, which includes `kl`)
   - units (274)
   - battery (261)
6. **Stored measurements** (cmd 271). The request carries `STORED_MEASURE_ACTION` (276): `cmd:u8, rc:s8`.
   - `cmd=0` → `STORED_MEASURE_STATUS` (277): `count:s16, oldest_time:s32, wifi_configured:s8`.
   - `cmd=1` → a multi-message list of records:
     - `STORED_MEASURE_META` (278): `uid:u32, valid:u8, ids:(u8 length + u32 array), attrib:u8, time:u32`, where `time` is UTC epoch seconds and applies to the data that follows. **Observed:** valid=1 with a 3-slot array, so only the first `valid` IDs mean anything. User IDs and `uid` aren't reliable keys.
     - `STORED_MEASURE_DATA` (279): `value:s32, type:u16, exponent:s16`; real value = value × 10^exponent.
     - Optional extras attach to the preceding data: `STORED_MEASURE_META_EXTEND` (299, algorithm), position, algorithm parameters, firmware version.
   - `cmd=2` is sent only **after** the app has uploaded the data to the cloud. It probably deletes the stored records, so we never send it by default.
7. **End.** We send `SYNC_OK` (277) and then DISCONNECT (272).
   - **reported** (two independent projects): without SYNC_OK the scale may ignore the next connection, and SYNC_OK neither deletes nor marks readings.
   - **app:** the phone app sends DISCONNECT without SYNC_OK for this scale.
   - We also echo a SYNC_OK the scale sends as a device request.
8. **De-duplication.** Every sync returns the scale's whole store, and one weigh-in arrives as several groups with the same timestamp (body composition, heart rate). Merge by `(time, measure type)`.

Measurement type codes we expect:

| Code | Measurement | Source |
|---|---|---|
| 1 | weight (kg) | app |
| 5 | fat-free mass | app |
| 6 | fat ratio (%) | app |
| 8 | fat mass | app |
| 11 | heart rate | app |
| 76 | muscle mass | app |
| 77 | body water | app |
| 88 | bone mass | public API, unconfirmed |

Error codes (cmd 256, `CMD_ERROR` (272): `cmd:u16, err:s32`):

| Code | Meaning |
|---|---|
| −2 | busy |
| −3 | unsupported |
| −4 | rejected |
| −5 | not authenticated |
| −8 | invalid arguments |
| −9 | arguments not set |

## Advertising — from app analysis
The app's background scanner matches either of two advertisements:
- the "WITH" service-UUID family, where the model is in group 4 and the MAC in the last group;
- service data on **0xFD77**. It starts with a u16 (version in the top nibble, model in the low 12 bits), followed by nibble-packed TLVs.
  - Type 1 is a flags byte: bit0 installed, bit1 sync requested, bit2 wake-up.
  - Type 2 is the MAC.
  - Type 3 is a short salted identity hash.

The app connects when the scale advertises *installed + sync requested*. That's the weigh-in trigger we need in Bluetooth mode. The nibble order in the TLV headers still has to be confirmed on a real Bluetooth-mode advertisement.

## Wi-Fi vs Bluetooth mode — from app analysis
- **Wi-Fi mode has no "also sync over Bluetooth" setting.**
- The mode is set during a BLE session, in setup or from the app's "Wi-Fi configuration" device menu:
  - **Bluetooth mode:** a Wi-Fi settings command with Wi-Fi disabled.
  - **Wi-Fi mode:** Wi-Fi scan + connect with credentials.
  - We do this from the official app, never ourselves.

## The secret `kl` — from app analysis
- `kl` is created on Withings' servers when the scale is associated with an account.
- The app downloads it with the device association data, stores it locally, and pushes it to the scale during setup and syncs.
- **The scale never reveals it.**
- `PROBE_REPLY.secret` is a different value, used by the app to open a server session on the scale's behalf.

## Never send
- ASSOCIATION_KEYS_SET (308)
- SETUP_OK (275)
- SCALE_SESSION (269)
- user/unit writes (274)
- Wi-Fi commands
- firmware-update commands
- factory reset
- STORED_MEASURE `cmd=2`, unless the user opts into deleting records from the scale
