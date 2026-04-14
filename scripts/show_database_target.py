import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Config


def _mask_database_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw or "@" not in raw or "://" not in raw:
        return raw

    scheme, remainder = raw.split("://", 1)
    credentials, host_part = remainder.split("@", 1)
    if ":" not in credentials:
        return f"{scheme}://***@{host_part}"

    username, _password = credentials.split(":", 1)
    return f"{scheme}://{username}:***@{host_part}"


def main() -> int:
    payload = {
        "database_backend": Config.DATABASE_BACKEND,
        "database_path": str(Path(Config.DATABASE).expanduser().resolve()),
        "database_url_masked": _mask_database_url(Config.DATABASE_URL),
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
