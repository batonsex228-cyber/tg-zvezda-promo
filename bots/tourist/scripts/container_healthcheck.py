"""Probe the private FastAPI readiness endpoint, never an external domain."""
import json
import sys
import urllib.request


def check(url='http://127.0.0.1:8000/ready'):
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            result = json.load(response)
            return response.status == 200 and result.get('ready') is True
    except (OSError, ValueError, TimeoutError):
        return False


if __name__ == '__main__':
    sys.exit(0 if check() else 1)
