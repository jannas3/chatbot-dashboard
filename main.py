import logging
import sys

from bot.config import get_settings
from bot.telegram_app import build_application


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main() -> None:
    configure_logging()
    settings = get_settings()
    application = build_application(settings)
    logging.getLogger(__name__).info("Bot inicializado", extra={"event": "startup"})
    application.run_polling(allowed_updates=[])


if __name__ == "__main__":
    main()


