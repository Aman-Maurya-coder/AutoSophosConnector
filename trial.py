import requests

try:
    r = requests.get("https://clients3.google.com/generate_204", timeout=5)
    print("status:", r.status_code)
    print("url:", r.url)
except Exception as e:
    print(type(e).__name__)
    print(e)