import argparse
import asyncio
import logging
import os
import pathlib
import sys

from .debug import make_sink

PROJECT = pathlib.Path(__file__).resolve().parent.parent


def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog="python -m monke", description="Run the Town of Monke bot.")
    ap.add_argument("--supervise", action="store_true",
                    help="run the bot as a child process and restart it after a crash (back-off 1 to 60 s)")
    ap.add_argument("--new-db", action="store_true",
                    help="allow starting with a brand new database in a server that is already set up")
    ap.add_argument("--force-takeover", action="store_true",
                    help="start even if another copy seems to be running (use after a hard crash)")
    ap.add_argument("--debug", action="store_true",
                    help="print every role, private message and decision to this console (also MONKE_DEBUG=1)")
    ap.add_argument("--debug-file", metavar="PATH", help="also write the debug lines to a file")
    ap.add_argument("--debug-chat", action="store_true", help="debug mode also prints what players type")
    return ap.parse_args(argv)


async def amain(token: str, db_path: str, args, sink) -> int:
    from .adapter.bot import MonkeBot
    from .service.instance import AlreadyRunning
    from .service.store import DatabaseDamaged
    from .shutdown import install_signal_handlers

    bot = MonkeBot(db_path, sink=sink, new_db=args.new_db, force_takeover=args.force_takeover)
    install_signal_handlers(asyncio.get_running_loop(), lambda: asyncio.ensure_future(bot.close()))
    try:
        async with bot:
            await bot.start(token)
    except AlreadyRunning:
        print(bot.exit_message)
        return bot.exit_code
    except DatabaseDamaged as e:
        print(e)
        return 4
    if bot.exit_message:  # the wrong-folder guard
        print(bot.exit_message)
    return bot.exit_code


def main(argv=None) -> None:
    args = parse_args(argv)
    if args.supervise:
        from .supervisor import child_command, supervise
        sys.exit(supervise(child_command(argv)))
    try:  # optional convenience: read DISCORD_TOKEN from a .env file in the current folder
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        sys.exit("Set DISCORD_TOKEN (environment variable, or a .env file next to where you run the bot).")
    from .logsetup import setup_logging
    log_path = setup_logging(str(PROJECT / "logs"))
    db_path = os.path.abspath(os.environ.get("MONKE_DB") or PROJECT / "monke.db")  # REL-2: never relative to the cwd
    logging.getLogger("monke").info("database: %s  log: %s", db_path, log_path)
    print(f"Database: {db_path}\nLog file: {log_path}")
    debug = args.debug or os.environ.get("MONKE_DEBUG", "") not in ("", "0")
    sink = make_sink(debug, args.debug_file, args.debug_chat)
    sys.exit(asyncio.run(amain(token, db_path, args, sink)))


if __name__ == "__main__":
    main()
