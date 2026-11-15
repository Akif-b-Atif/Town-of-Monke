"""All player-visible text lives here (XC-1). Never write prose inline."""
from .. import constants as C

# Phase emoji (TRN-3). One dict, keyed by the engine's phase constants.
PHASE_EMOJI = {
    C.DAY_1: "☀️",
    C.DAY: "☀️",
    C.NOON: "🗳️",
    C.TRIAL_DEFENSE: "🛡️",
    C.TRIAL_VERDICT: "⚖️",
    C.AFTERNOON: "🌇",
    C.NIGHT: "🌙",
}

# Banner heading per phase (TRN-3). Night uses the night number, the others the day number.
PHASE_TITLE = {
    C.DAY_1: "Day {day}",
    C.DAY: "Day {day}",
    C.NOON: "Noon, Day {day}",
    C.TRIAL_DEFENSE: "Defense, Day {day}",
    C.TRIAL_VERDICT: "Verdict, Day {day}",
    C.AFTERNOON: "Afternoon, Day {day}",
    C.NIGHT: "Night {night}",
}
BANNER_ENDS = "Ends {rel} ({clock}) · {alive} alive"
BANNER_VOTES = "Votes needed for a trial: {needed}"

# One line per phase-change reason code (TRN-2). `night_resolved` is a plain placeholder until the
# dawn report (QOL-3) exists.
TRANSITION_LINES = {
    "game_start": "The game begins.",
    "day1_timer": "Day 1 is over. Night 1 begins.",
    "day_timer": "Discussion is over. Voting is open.",
    "trial_majority": "**{target}** has {votes}/{needed} votes and goes on trial.",
    "defense_timer": "The defense is over. Cast your verdict.",
    "verdict_guilty": "**{target}** was found guilty ({guilty}–{innocent}) and lynched. It is now Afternoon.",
    "verdict_pardon": "**{target}** was pardoned ({guilty}–{innocent}). {trials_left} more trial(s) possible today. Voting reopens.",
    "three_innocent": "Three accused have been pardoned today. No more trials. It is now Afternoon.",
    "noon_no_trial": "The town could not agree on anyone to lynch. It is now Afternoon.",
    "noon_timeout_after_pardon": "Time ran out before another trial. It is now Afternoon.",
    "afternoon_timer": "The sun has set. Night {night} begins.",
    "night_resolved": "Day {day} dawns.",
}
ADMIN_SKIP_PREFIX = "An admin ({name}) ended the phase early."
UNKNOWN_REASON = "The phase changed."

# Game start (TRN-4)
ROSTER_TITLE = "Town of Monke: the game begins"
ROSTER_ROLELIST = "Role list"

# Admin messages (ADM)
SKIP_TOO_SOON = "The phase just changed. Check `monke status` before skipping again."
GAME_ALREADY_RUNNING = "A game is already starting or running."
NO_ADMINS = "Nobody has Monke Admin. Give the role to someone in Server Settings → Roles."
ADMIN_ONLY = "Only someone with the Monke Admin role can do that."
ADMINS_LIST = "Current Monke Admin holders: {names}"

SETUP_COMPLETE = (
    "Setup complete. Run games in <#{commands_channel_id}>. Everyone can read that channel, "
    "but only **Monke Admin** can write there.\n"
    "Server owners and Administrators can see every channel, so they should not play."
)

# Spoiler-safe notices for Monke Commands (XC-7): no roles, no seed, no traceback.
ENGINE_ERROR_PAUSED = (
    "Game {game_id}: The game was paused because of an internal error. "
    "Use `monke resume` or `monke abort`."
)
GAME_PAUSED = "The game is paused. Use `monke resume` or `monke abort`."

# Archive (ARC)
GAME_LOGGED = "Game channels are logged for the post-game archive."  # ARC-14
ARCHIVE_FAILED = "Archive failed. Chats were NOT deleted. Run `monke export` to retry."  # ARC-10
ARCHIVE_PURGE_FAILED = ("The archive is saved in Monke Commands, but clearing the game channels failed. "
                        "Run `monke export` to retry.")
EXPORT_LIVE_REFUSED = "Archives are only available after the game ends."  # ARC-12
ARCHIVE_STILL_RUNNING = ("The previous game is still being archived. Wait for the archive to appear in "
                         "Monke Commands, or run `monke export`.")
EXPORT_DONE = "Archive posted in Monke Commands."
EXPORT_DONE_AND_CLEARED = "Archive posted in Monke Commands and the game channels were cleared."
EXPORT_FAILED = "The archive failed again. Chats were NOT deleted. Check the bot log."
SEPARATOR = ("────────────────────\n**GAME {game_id} OVER**\n{result}\n"
             "The logs are in #monke-commands.\nAnything below this line belongs to the next game.")
TEARDOWN_PENDING = ("A game's archive is not finished. Run `monke export` first, or use "
                    "`monke teardown --force` to delete everything anyway.")
