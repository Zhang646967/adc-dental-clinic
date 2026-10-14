"""Private listener health check, with the trusted proxy's explicit headers."""
import os
import urllib.request

request = urllib.request.Request('http://127.0.0.1:8000/health/', headers={
    'Host': os.environ['ADC_PUBLIC_HOST'], 'X-Forwarded-Proto': 'https',
})
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open(request, timeout=4) as response:
    if response.status != 200:
        raise SystemExit(1)
