"""نقطه‌ی ورود بات حسابیار: ``python -m hesabyar``"""
from __future__ import annotations

import logging
import sys

from .bot.app import build_application
from .config import load_settings


def main() -> None:
    # همه‌ی لاگ‌ها به stdout (روی Railway دیسک بین دیپلوی‌ها پاک می‌شود).
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
    settings = load_settings()
    application = build_application(settings)
    logging.getLogger(__name__).info("حسابیار در حال اجراست…")
    application.run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()
