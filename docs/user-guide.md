# User guide

Draft notes for end users. They will become the README / integration docs.

## Switch the scale to Bluetooth mode

The local integration needs the scale in **Bluetooth mode**. In Wi-Fi mode the scale uploads straight to Withings and never announces new readings over Bluetooth.

> **Wi-Fi mode is not supported.** We tested it: after a weigh-in in Wi-Fi mode, an unpaired scale stays silent on Bluetooth. Another project, [esphome-withings-wpp](https://github.com/NavistAuLabs/esphome-withings-wpp), reports that Wi-Fi mode keeps working after a one-time passkey pairing from an ESP32. This integration pairs with the scale too (since 0.3.0), but whether a paired scale in Wi-Fi mode advertises after a weigh-in is untested here. If you need the Withings cloud and local data at the same time, that project is the known option.

Tested on a Body Smart (WBS13), Withings app 26.40.

1. In the Withings app, open your scale's page.
2. Tap **Wi-Fi configuration**.
3. Press and hold the button under the scale for about **3 seconds**. The configuration screen appears on your phone.
4. Tap **Other options**, then **I don't have a Wi-Fi**.

Then:
- The scale no longer uploads to Withings by itself. The Withings app still uploads readings when your phone syncs with the scale over Bluetooth.
- To undo it, repeat the steps and pick your Wi-Fi network instead.
- Buttons: a **short** press opens the on-scale menu. A **3-second hold** starts configuration with the app. Avoid the **Reset** entry in the on-scale menu: it wipes the scale's setup.

## Set up Home Assistant

You need:
- Home Assistant 2026.10 or newer
- a Bluetooth adapter, or an ESPHome Bluetooth proxy, within a few meters of the scale
- the scale in Bluetooth mode (above)

1. Install the integration (HACS custom repository, or copy `custom_components/withings_local` into your config folder) and restart Home Assistant.
2. Step on the scale. When it advertises, Home Assistant offers **Withings Local (Bluetooth)** as a discovered device. You can also add it from **Settings → Devices & services → Add integration** right after a weigh-in.
3. Choose how to give it the scale's key:
   - **Fetch the key with my Withings login.** Your email and password go to Withings once and are not stored.
   - **Enter the key myself.** Paste the value from `tools/fetch_kl.py`.
4. **Pair with the scale (once).** The scale only shares measurements over a Bluetooth connection paired with the 6-digit code on its display.
   1. Hold the button under the scale for **3 seconds**.
   2. Choose **Pair now**.
   3. Enter the code the scale shows. You have about 30 seconds.

   Afterwards the scale may show **"Setup failed"**. That's expected: it means setup mode ended without the Withings app. The pairing is stored, and the scale keeps working as before.
5. Weigh in. Within about a minute of the reading finishing, the sensors update.

If the pairing is lost later (for example after a battery change), Home Assistant shows **Reauthentication required** for the integration. Open it and pair again. You can also re-pair at any time with **Reconfigure** from the integration's menu.

**Pairing needs a Bluetooth adapter connected to the Home Assistant host, on Linux (for example a Raspberry Pi's built-in Bluetooth or a USB dongle).** ESPHome Bluetooth proxies can't pair with a code yet. If you also use proxies, keep the scale closer to the paired adapter: Home Assistant may otherwise route the connection through a proxy that doesn't hold the pairing.

Notes:
- **The phone app can compete for the readings.** If your phone's Withings app connects to the scale first, it uploads the readings and then deletes them from the scale, so Home Assistant may miss that weigh-in. Home Assistant never deletes readings. Put the adapter or proxy close to the scale.
- **One device per person.** Each Withings user gets their own device ("Body Smart (name)") with their latest weigh-in. Names come from your Withings account if you set up with the login; with a pasted key they show as "User 1", "User 2", and you can rename them in Home Assistant. **Guest** weigh-ins get a separate device with weight only. The scale's own device shows the battery level and the last sync.
