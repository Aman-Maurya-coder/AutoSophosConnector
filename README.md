# AutoSophosWifiConnector

## Credential Storage

- Username and password are stored securely in Windows Credential Manager using `keyring`.
- The app does not store passwords in `config.json`.

## First Run Behavior

- On startup, the app checks whether both username and password exist in keyring.
- If credentials are missing, a Tkinter window opens and asks for them.
- After successful save, the app continues automatically.

## Updating Credentials

- Use the tray menu credential option to open the Tkinter window again.
- Saving new values overwrites the secure keyring entries.

## College SSID Lock

- The app can be locked to only attempt login on your college Wi-Fi SSID.
- Set `COLLEGE_WIFI_SSID` in `config.py` to your exact SSID name.
- Keep `SSID_LOCK_ENABLED=True` to enforce the lock.
- When not on the configured SSID, status becomes:
	- `COLLEGE_WIFI_NOT_CONNECTED` (college SSID is visible but you are on another network)
	- `COLLEGE_WIFI_NOT_AVAILABLE` (college SSID not visible nearby)

### Where to get your SSID (Windows)

- Command Prompt / PowerShell: run `netsh wlan show interfaces` and copy the value shown after `SSID`.
- Windows UI: Settings > Network & Internet > Wi-Fi > Hardware properties, then read Network name (SSID).
