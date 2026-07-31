from __future__ import annotations

from .config import Settings
from .feed import migrate_feed_base


def main() -> int:
    settings = Settings.from_env(require_api_key=False)
    migrate_feed_base(settings.feed_path, settings.server_base_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
