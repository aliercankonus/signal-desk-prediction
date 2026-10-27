from __future__ import annotations

import json
import sys
import urllib.request


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    url = argv[0] if argv else "http://127.0.0.1:8080/health"
    with urllib.request.urlopen(url, timeout=5) as resp:
        data = json.loads(resp.read().decode())
    if data.get("status") != "ok" or data.get("execution_enabled") is not False:
        print(data)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
