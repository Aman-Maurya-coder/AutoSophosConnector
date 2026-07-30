LOGIN_URL="http://192.168.100.1:8090/login.xml"

LOGOUT_URL="http://192.168.100.1:8090/logout.xml"

CHECK_URL="http://clients3.google.com/generate_204"

GATEWAY="http://192.168.100.1:8090"

# Gateway IP used to detect college network presence.
# Checked via GetAdaptersInfo (iphlpapi) — no SSID read, no location ping.
COLLEGE_GATEWAY_IP="192.168.100.1"

# Legacy: no longer used for connection detection (SSID access triggers
# the Windows location indicator). Kept for reference only.
COLLEGE_WIFI_SSID="IIITU_Wireless"

SSID_LOCK_ENABLED=True

CHECK_INTERVAL=12


HEADERS={

"Accept":"*/*",

"Connection":"keep-alive",

"Content-Type":"application/x-www-form-urlencoded",

"Origin":GATEWAY,

"Referer":GATEWAY+"/httpclient.html",

"User-Agent":"Mozilla/5.0"

}