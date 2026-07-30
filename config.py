LOGIN_URL="http://192.168.100.1:8090/login.xml"

LOGOUT_URL="http://192.168.100.1:8090/logout.xml"

# Used by the soft-auth-check to probe whether the Sophos portal is
# intercepting traffic (indicates session expiry) without needing DNS.
GATEWAY_AUTH_CHECK_URL="http://192.168.100.1:8090/httpclient.html"

GATEWAY="http://192.168.100.1:8090"

# Gateway IP used to detect college network presence via TCP socket probe.
COLLEGE_GATEWAY_IP="192.168.100.1"

# Legacy: no longer used for connection detection (SSID access triggers
# the Windows location indicator). Kept for reference only.
COLLEGE_WIFI_SSID="IIITU_Wireless"

SSID_LOCK_ENABLED=True

# ---------------------------------------------------------------------------
# Health-check endpoints (Layer 2 — internet connectivity)
# Endpoints are probed sequentially in order. A check succeeds on the first SUCCESS.
# ---------------------------------------------------------------------------
HEALTH_ENDPOINTS = [
    # name used in logs, URL
    ("Google204",   "https://clients3.google.com/generate_204"),
    ("Cloudflare",  "https://www.cloudflare.com/cdn-cgi/trace"),
    ("Example",     "https://example.com"),
]

# Logging mode identifiers
MODE_PRODUCTION = "PRODUCTION"
MODE_DEBUG = "DEBUG"
MODE_DIAGNOSTIC = "DIAGNOSTIC"


# Per-endpoint timeouts (connect, read) in seconds.
HEALTH_CONNECT_TIMEOUT = 4
HEALTH_READ_TIMEOUT    = 5

# How many consecutive internet-check failures before we escalate.
# Each failure = one monitor tick = CHECK_INTERVAL seconds.
MAX_INTERNET_FAILURES = 4

# How many consecutive captive-portal detections before we re-login.
MAX_AUTH_FAILURES = 2

# Patterns in response URL or body that indicate the Sophos captive portal
# has intercepted the request (session expired).
CAPTIVE_PORTAL_PATTERNS = [
    "192.168.100.1:8090",
    "httpclient.html",
    "login.xml",
    "producttype=0",
]

# ---------------------------------------------------------------------------
# Monitor timing
# ---------------------------------------------------------------------------
CHECK_INTERVAL=12

# Grace period after a successful login before the first health-check fires.
POST_LOGIN_GRACE = 5


HEADERS={

"Accept":"*/*",

"Connection":"keep-alive",

"Content-Type":"application/x-www-form-urlencoded",

"Origin":GATEWAY,

"Referer":GATEWAY+"/httpclient.html",

"User-Agent":"Mozilla/5.0"

}