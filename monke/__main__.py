import argparse
import logging
import os
import sys

from .adapter.bot import MonkeBot
from .debug import make_sink


def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog="python -m monke", description="Run the Town of Monke bot.")
    ap.add_argument("--debug", action="store_true",
                    help="print every role, private message and decision to this console (also MONKE_DEBUG=1)")
    ap.add_argument("--debug-file", metavar="PATH", help="also write the debug lines to a file")
    ap.add_argument("--debug-chat", action="store_true", help="debug mode also prints what players type")
    return ap.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    try:  # optional convenience: read DISCORD_TOKEN from a .env file in the current folder
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        sys.exit("Set DISCORD_TOKEN (environment variable, or a .env file next to where you run the bot).")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    debug = args.debug or os.environ.get("MONKE_DEBUG", "") not in ("", "0")
    sink = make_sink(debug, args.debug_file, args.debug_chat)
    MonkeBot(os.environ.get("MONKE_DB", "monke.db"), sink=sink).run(token, log_handler=None)


if __name__ == "__main__":
    main()
