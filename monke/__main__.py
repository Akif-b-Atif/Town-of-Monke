import logging
import os
import sys

from .adapter.bot import MonkeBot


def main() -> None:
    try:  # optional convenience: read DISCORD_TOKEN from a .env file in the current folder
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        sys.exit("Set DISCORD_TOKEN (environment variable, or a .env file next to where you run the bot).")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    MonkeBot(os.environ.get("MONKE_DB", "monke.db")).run(token, log_handler=None)


if __name__ == "__main__":
    main()
