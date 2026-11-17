"""Start-up guards that need no Discord (REL-2)."""
from __future__ import annotations

WRONG_FOLDER = ("This looks like the wrong folder or a lost database: {path} did not exist before this start, but "
                "this bot is already set up in a server (it has a 'Town of Monke' category). Start the bot from the "
                "folder that holds your monke.db, or restore it from the backups folder. If you really want a fresh "
                "database, start with --new-db.")


def looks_like_wrong_folder(existed_before: bool, server_has_monke_category: bool, new_db: bool) -> bool:
    return (not existed_before) and server_has_monke_category and not new_db
