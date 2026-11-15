"""The registry of text keys (TXT-3): which keys exist, which {placeholders} each may use, and how many variants
it needs. Role and ability keys are generated from the role registry, so a role added later automatically requires
its intro, goal, tips, reveal, wiki and ability-label keys.

Table format, one key per line:  key | placeholders (space separated) | minimum variants [| r]
`r` marks a reserved key: it is in the shipped file but no rule uses it yet, so it may be absent."""
from __future__ import annotations

from dataclasses import dataclass

from ..roles import all_defs


@dataclass(frozen=True)
class KeySpec:
    placeholders: tuple = ()
    min_variants: int = 1
    reserved: bool = False


_TABLE = """
game.start.public||1
game.rolelist.header|count|1
phase.day1|day|1
phase.dawn|day|3
phase.noon|day time|3
phase.afternoon|day time|3
phase.night|night time|3
phase.warning|time|3
phase.paused||1
phase.resumed||1
night.nudge|time|2
phase.skip.progress|count needed|1
dawn.no_deaths||3
dawn.deaths_intro||2|r
dawn.survivors|alive|2
dawn.stalemate_warning|count|1
death.cause.mafia|player|3
death.cause.serial_killer|player|3
death.cause.veteran|player|3
death.cause.jailor|player|3
death.cause.jester_haunt|player|3
death.cause.lynched|player|3
death.cause.abandoned|player|2
death.cause.moderated|player|1
death.cause.multiple|player causes|2
death.will|player will|2
death.no_will|player|2|r
death.note|note|2
vote.cast|player target count needed|3
vote.change|player target previous count needed|3
vote.remove|player target|3
noon.no_trial||3
trial.start|target|3
trial.defense|target time|3
trial.verdict|target time|3
trial.guilty|target count needed|3
trial.pardon|target|3
trial.reveal|count needed|1
trial.three_innocent||2
jester.win_public|player|2
jail.prisoner.notified||3
jail.channel.open||2
jail.jailor.prompt|target|2
jail.release||2
jail.target_in_jail||3
jailor.executed_notice||2
jailor.exec_disabled||2
block.you_were_blocked||3
block.target_immune||2
attack.saved_target||3
attack.doctor_target_attacked||3
attack.too_strong||3
attack.target_healed||2
attack.survived||3|r
vet.alert_on||2|r
vet.shot_visitor||2
vet.no_alerts||1
sk.blocked_rampage||2
sk.jailed_rampage||2
mafia.order_received|target|3
mafia.godfather_takes_over||2
sheriff.result.innocent|target|3
sheriff.result.guilty|target|3
consig.result|target role|3
doctor.self_heal_used||1
doctor.no_self_heal||1
jester.haunt_prompt||2
jester.haunt_done|target|2
action.confirm.heal|target|1
action.confirm.block|target|1
action.confirm.sheriff|target|1
action.confirm.consig|target|1
action.confirm.mafia_kill|target|1
action.confirm.mafia_order|target|1
action.confirm.sk_kill|target|1
action.confirm.alert||1
action.confirm.alert_off||1
action.confirm.no_action||1
action.confirm.jail|target|1
action.confirm.jail_clear||1
action.confirm.execute||1
action.confirm.execute_cancel||1
action.confirm.haunt|target|1
action.confirm.verdict.guilty||1
action.confirm.verdict.innocent||1
action.confirm.verdict.abstain||1
action.confirm.confirm||1
end.town||2
end.mafia||2
end.sk||2
end.draw||2
end.jester||2
end.recap.header||1
end.recap.day|day|1
end.recap.night|night|1
end.recap.lynch|target count needed|1
end.recap.jail|target|1
end.recap.execute|target|1
end.recap.death|player causes|1
end.rematch||1
graveyard.welcome|player|3
graveyard.rules||1
afk.warning|count|2
afk.removed|player|2
will.saved||1
will.too_long|count|1
will.disabled||1
deathnote.saved||1
deathnote.too_long|count|1
deathnote.not_allowed||1
deathnote.disabled||1
lobby.created||2
lobby.joined||2
lobby.left||1
lobby.full||1
lobby.already_in||1
lobby.dm_closed||1
lobby.start_blocked.count|count|1
lobby.start_blocked.rolelist|causes|1
lobby.cancelled||1
lobby.expired||1
lobby.started||1
admin.setup.done||1
admin.teardown.confirm||1
admin.teardown.done||1
admin.abort.confirm||1
admin.aborted||1
admin.paused||1
admin.resumed||1
admin.extended|time|1
admin.skipped||1
admin.replaced|slot player target|1
admin.modkill.confirm|target|1
admin.settings.saved||1
admin.reload.ok|count|1
admin.reload.failed|causes|1
admin.diagnose.ok||1
admin.diagnose.problems||1
admin.export.ready||1
admin.restarted||1
admin.dm_failed|player|1
error.dead||1
error.not_in_game||1
error.no_game||1
error.game_running||1
error.not_admin||1
error.wrong_phase|causes time|1
error.vote_wrong_phase|time|1
error.stale_prompt||1
error.unknown_target||1
error.dead_target||1
error.self_target||1
error.no_uses||1
error.already_pardoned||1
error.defendant_cannot_vote||1
error.bad_option|causes target|1
error.bad_option_nosuggest|causes|1
error.bad_duration|causes|1
error.below_minimum|time setting|1
error.bad_rolelist|causes|1
error.player_count|count|1
error.rolelist_count|count needed|1
error.no_prisoner||1
error.generic||1
error.game_ended||1
error.game_not_running||1
error.already_started||1
error.not_paused||1
error.paused||1
error.not_started||1
error.no_ability||1
error.cant_use||1
error.no_target_needed||1
error.no_verdict||1
error.bad_verdict||1
error.setting_invalid|causes|1
error.rolelist_unknown_token|causes|1
error.rolelist_jailor||1
error.rolelist_godfather||1
error.rolelist_unique|role|1
error.rolelist_pool|group|1
error.distinct_players||1
error.no_such_game||1
ui.emoji.day||1
ui.emoji.noon||1
ui.emoji.defense||1
ui.emoji.verdict||1
ui.emoji.afternoon||1
ui.emoji.night||1
ui.emoji.death||1
ui.emoji.trial||1
ui.emoji.ok||1
ui.emoji.pause||1
ui.emoji.winner||1
ui.title.day|day|1
ui.title.defense|day|1
ui.title.verdict|day|1
ui.when.day|day|1
ui.when.noon|day|1
ui.when.night|night|1
ui.banner.status|rel alive|1
ui.banner.votes|needed|1
ui.banner.paused||1
transition.day1_timer||1
transition.day_timer||1
transition.defense_timer||1
transition.afternoon_timer|night|1
transition.admin_skip|name|1
transition.unknown||1
transition.skip_early||1
ui.phase.day||1
ui.phase.night||1
ui.duration.second|count|1
ui.duration.seconds|count|1
ui.duration.minute|count|1
ui.duration.minutes|count|1
ui.duration.hour|count|1
ui.duration.hours|count|1
ui.role.list.line|slot name|1
ui.roster.title||1
ui.roster.players||1
ui.game_logged||1
ui.card.title|role|1
ui.card.alignment||1
ui.card.attack||1
ui.card.defense||1
ui.card.abilities||1
ui.card.goal||1
ui.card.tips||1
ui.card.team||1
ui.card.teammate|player role|1
ui.align.town||1
ui.align.mafia||1
ui.align.neutral||1
ui.level.0||1
ui.level.1||1
ui.level.2||1
ui.level.3||1
ui.prompt.tonight||1
ui.prompt.today||1
ui.prompt.deadline_night|rel|1
ui.prompt.deadline_day||1
ui.prompt.current||1
ui.prompt.do_nothing||1
ui.prompt.on||1
ui.prompt.off||1
ui.prompt.expired|what|1
ui.cause.mafia||1
ui.cause.serial_killer||1
ui.cause.veteran||1
ui.cause.jailor||1
ui.cause.jester_haunt||1
ui.cause.lynched||1
ui.cause.abandoned||1
ui.cause.moderated||1
ui.join.and||1
ui.verdict.guilty|count players|1
ui.verdict.innocent|count players|1
ui.verdict.abstain|count players|1
ui.verdict.none||1
ui.trial.voters|players|1
ui.button.guilty||1
ui.button.innocent||1
ui.button.abstain||1
ui.end.title.town||1
ui.end.title.mafia||1
ui.end.title.sk||1
ui.end.title.draw||1
ui.end.title.aborted||1
ui.end.line|player role fate|1
ui.end.footer|reason day|1
ui.role.unknown||1
admin.skip_too_soon||1
admin.player_left|player|1
admin.no_admins||1
admin.admins_list|names|1
admin.engine_error|game_id|1
admin.game_paused||1
admin.setup.details|channel|1
admin.teardown.pending||1
admin.teardown.running||1
admin.teardown.nothing||1
admin.setup.missing_perms|causes|1
admin.setup.hierarchy|role|1
admin.start.starting||1
admin.start.cant|causes|1
admin.start.dm_failed|causes|1
admin.status|status phase rel alive total|1
admin.abort.done||1
ui.vote.recorded||1
ui.vote.removed||1
ui.resend.done|count|1
error.nothing_to_do||1
error.archive_expired|days|1
rel.quarantined|game_id|1
rel.structures_missing|causes|1
rel.players_left|count|1
rel.starting_cancelled||1
rel.jail_gap||1
rel.jailor_gap|count digest|1
rel.restarted_admin|game_id time|1
rel.restarted_town||1
rel.shutdown_notice||1
rel.render_failed|game_id|1
rel.owner_alert|game_id|1
error.shutting_down||1
error.bot_player||1
error.start_usage||1
info.alive.header|count|1
info.alive.dead_header|count|1
info.alive.dead_line|player role causes day|1
info.votes.header||1
info.votes.line|target count players|1
info.votes.needed|needed|1
info.votes.none||1
info.votes.closed||1
info.rolelist.header|count|1
info.rolelist.default|count|1
info.timer.running|phase rel|1
info.timer.paused|phase|1
info.timer.over||1
ui.phasename.day_1|day|1
ui.phasename.day|day|1
ui.phasename.noon|day|1
ui.phasename.defense|day|1
ui.phasename.verdict|day|1
ui.phasename.afternoon|day|1
ui.phasename.night|night|1
help.header||1
help.line|usage text|1
help.group.player||1
help.group.admin||1
help.group.server||1
help.nothing||1
confirm.what.skip||1
confirm.what.replace|player target|1
confirm.what.quickstart||1
confirm.expired||1
confirm.cancelled||1
panel.placeholder||1
error.wrong_channel||1
error.not_set_up||1
error.missing_arg|causes|1
help.vote||1
help.unvote||1
help.votes||1
help.alive||1
help.rolelist||1
help.timer||1
help.role||1
help.help||1
help.resend||1
help.journal||1
help.will||1
help.deathnote||1
help.start||1
help.status||1
help.skip||1
help.abort||1
help.resume||1
help.pause||1
help.extend||1
help.modkill||1
help.replace||1
help.settings||1
help.reloadtext||1
help.diagnose||1
help.export||1
help.admins||1
help.setup||1
help.teardown||1
help.lobby||1
help.arg.player||1
help.arg.count||1
help.arg.game_id||1
help.arg.players||1
help.arg.roles||1
help.arg.options||1
help.arg.force||1
help.arg.time||1
help.arg.reason||1
help.arg.old||1
help.arg.new||1
help.arg.text||1
help.arg.fix||1
help.arg.settings||1
help.arg.action||1
ui.button.join||1
ui.button.leave||1
ui.button.start||1
ui.button.edit_settings||1
ui.button.edit_rolelist||1
ui.button.cancel||1
ui.button.confirm||1
ui.button.unvote||1
ui.button.skip_ahead||1
ui.button.play_again||1
ui.button.edit_will||1
ui.button.edit_note||1
ui.button.yes||1
ui.button.no||1
lobby.embed.title||1
lobby.embed.opened_by|name|1
lobby.embed.players|count|1
lobby.embed.rolelist|count|1
lobby.embed.rolelist_default||1
lobby.embed.settings||1
lobby.embed.empty||1
lobby.embed.footer|time|1
lobby.modal.settings_title||1
lobby.modal.settings_label||1
lobby.modal.rolelist_title||1
lobby.modal.rolelist_label||1
lobby.modal.rolelist_hint||1
lobby.where|channel|1
lobby.none_open||1
lobby.added|player|1
lobby.removed|player|1
lobby.rematch_empty||1
confirm.quickstart.details|players rolelist settings|1
ui.recap.title|night|1
ui.journal.header||1
ui.journal.empty||1
ui.journal.entry|when text|1
will.modal.title||1
will.modal.label||1
deathnote.modal.title||1
deathnote.modal.label||1
ui.banner.skip|count needed|1
afk.admin_warning|player count|1
diagnose.check.permissions||1
diagnose.fix.permissions||1
diagnose.check.hierarchy||1
diagnose.fix.hierarchy||1
diagnose.check.channels||1
diagnose.fix.channels||1
diagnose.check.overwrites||1
diagnose.fix.overwrites||1
diagnose.check.slot_roles||1
diagnose.fix.slot_roles||1
diagnose.check.intents||1
diagnose.fix.intents||1
diagnose.check.database||1
diagnose.fix.database||1
diagnose.check.backups||1
diagnose.fix.backups||1
diagnose.check.flavour||1
diagnose.fix.flavour||1
diagnose.check.games||1
diagnose.fix.games||1
diagnose.check.instance||1
diagnose.fix.instance||1
diagnose.check.debug||1
diagnose.fix.debug||1
diagnose.title||1
diagnose.line.ok|label|1
diagnose.line.bad|label detail fix|1
diagnose.debug.on||1
diagnose.debug.off||1
diagnose.fix.skipped_running||1
diagnose.fixed||1
ui.fate.survived||1
ui.fate.died|causes when|1
end.recap.investigation|player target text|1
end.recap.pardon|target count needed|1
admin.replace.test_dm||1
admin.settings.current|settings|1
admin.replace.not_member||1
admin.replace.is_playing||1
admin.modkill.done||1
archive.failed||1
archive.purge_failed||1
archive.live_refused||1
archive.still_running||1
archive.export.done||1
archive.export.done_cleared||1
archive.export.failed||1
archive.building||1
archive.separator|game_id result|1
archive.embed.title|game_id|1
archive.embed.result||1
archive.embed.length|minutes days|1
archive.embed.player|slot name role fate|1
"""


def _parse() -> dict:
    out: dict = {}
    for raw in _TABLE.strip().splitlines():
        parts = [p.strip() for p in raw.split("|")]
        key, ph, mn = parts[0], tuple(parts[1].split()), int(parts[2])
        out[key] = KeySpec(ph, mn, len(parts) > 3 and parts[3] == "r")
    return out


def _generated() -> dict:
    out: dict = {}
    for d in all_defs():
        out[f"role.{d.id}.intro"] = KeySpec(("wiki",))
        out[f"role.{d.id}.goal"] = KeySpec(("wiki",))
        out[f"role.{d.id}.tips"] = KeySpec(("wiki",))
        out[f"role.{d.id}.reveal"] = KeySpec(("player",))
        out[f"role.{d.id}.wiki"] = KeySpec(())
        out[f"role.{d.id}.name"] = KeySpec(())
        for ab in d.abilities:
            out[f"ability.{d.id}.{ab.id}.label"] = KeySpec(("count",))
    return out


TEXT_KEYS: dict = {**_parse(), **_generated()}
