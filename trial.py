import requests
import time

urls = [
    "https://clients3.google.com/generate_204",
    "https://www.google.com",
    "https://example.com",
    "https://1.1.1.1",
]

for url in urls:
    print(f"\nTesting {url}")
    try:
        start = time.time()
        r = requests.get(url, timeout=5)
        print("Status:", r.status_code)
        print("Time:", round(time.time() - start, 2), "s")
    except Exception as e:
        print(type(e).__name__, e)