"""Private, killable public REST request helper; no exchange credentials."""
import json
import sys

import requests


def main():
    try:
        url, symbol, limit = sys.argv[1:]
        with requests.get(url, params={"symbol": symbol, "limit": int(limit)},
                          timeout=(3, 10), stream=True) as response:
            if response.status_code != 200:
                print(json.dumps({"error": f"Snapshot HTTP {response.status_code}",
                                  "http_status": response.status_code}))
                return 1
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 2 * 1024 * 1024:
                    raise ValueError("Snapshot response exceeded 2 MiB")
                chunks.append(chunk)
        payload = json.loads(b"".join(chunks))
        print(json.dumps(payload))
        return 0
    except ValueError as exc:
        print(json.dumps({"error": str(exc), "fatal": True}))
        return 1
    except Exception as exc:
        print(json.dumps({"error": str(exc), "http_status": None}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

