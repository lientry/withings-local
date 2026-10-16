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

**Reported — not yet tried on our scale:**
- In normal (non-setup) sessions the scale answers PROBE with `PROBE_CHALLENGE` (296).
  - The challenge carries `mac:str` and 16 random bytes.
  - The app answers with `SHA1(challenge ‖ mac ‖ kl)` and its own challenge for the scale.
  - `kl` is a per-scale secret created when the scale is associated with an account.
- Reading measurements: `STORED_MEASURE` (271) with action 0 = state, 1 = get all, 2 = delete all. The session must end with `SYNC_OK` (277), or the scale ignores the next connection.
- In setup sessions the app must acknowledge `SETUP_OK` (275), otherwise the display shows "Setup failed". We deliberately don't acknowledge it.
- `ConnectReason` (280) values: 1 = user request (button), 2 = device request (weigh-in).
