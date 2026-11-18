"""Persistent components. DynamicItem custom IDs carry game_id + a freshness token + kind, so buttons
and menus survive restarts. Every click is re-validated by the engine (never trust the UI)."""
from __future__ import annotations

import re

import discord

from .. import constants as C
from ..engine import commands as K
from ..errors import Rejected

_GAME = r"[0-9a-f]+"


def _t(interaction, key: str, state=None, **vars) -> str:
    return interaction.client.presenter.composer.t(state, key, **vars)


def _find(interaction: discord.Interaction, game_id: str, kind: str, token: str):
    """Resolve (state, slot) or return (None, message)."""
    service = interaction.client.service
    state = service.find_by_game_id(game_id)
    if state is None or state.status != C.RUNNING:
        return None, _t(interaction, "error.stale_prompt")
    if kind == "verdict":
        if state.phase != C.TRIAL_VERDICT or str(state.phase_id) != token:
            return None, _t(interaction, "error.stale_prompt", state)
    elif state.token_for(kind.upper()) != token:
        return None, _t(interaction, "error.stale_prompt", state)
    slot = state.slot_of_user(interaction.user.id)
    if slot is None:
        return None, _t(interaction, "error.not_in_game", state)
    return (state, slot), None


async def _submit_action(interaction, game_id, kind, token, ability, target, toggle):
    found, err = _find(interaction, game_id, kind, token)
    if err:
        return await interaction.response.send_message(err, ephemeral=True)
    state, slot = found
    active = True
    if toggle:
        cur = state.night_actions.get(slot)
        active = not (cur is not None and cur.active)
    try:
        await interaction.client.service.submit(state.guild_id, K.SubmitAction(slot, ability, target, active))
    except Rejected as e:
        return await interaction.response.send_message(interaction.client.presenter.composer.error(e, state),
                                                       ephemeral=True)
    if toggle:
        choice = _t(interaction, "ui.prompt.on" if active else "ui.prompt.off", state)
    elif target is None:
        choice = _t(interaction, "ui.prompt.do_nothing", state)
    else:
        choice = interaction.client.presenter.name_of(state, target)
    base = (interaction.message.content or "").split("\n\n")[0]  # header and deadline; the choice follows
    await interaction.response.edit_message(
        content=f"{base}\n\n{_t(interaction, 'ui.prompt.current', state)}: **{choice}**")


class ActionSelect(discord.ui.DynamicItem[discord.ui.Select],
                   template=rf"monke:act:(?P<game>{_GAME}):(?P<kind>day|night):(?P<token>\w+):(?P<ability>[a-z_]+)"):
    def __init__(self, game, kind, token, ability, options=None):
        self.game, self.kind, self.token, self.ability = game, kind, token, ability
        super().__init__(discord.ui.Select(
            custom_id=f"monke:act:{game}:{kind}:{token}:{ability}",
            placeholder="Choose a target", options=options or [], min_values=1, max_values=1))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["game"], match["kind"], match["token"], match["ability"])

    async def callback(self, interaction: discord.Interaction):
        value = interaction.data["values"][0]
        await _submit_action(interaction, self.game, self.kind, self.token, self.ability,
                             None if value == "none" else int(value), toggle=False)


class ToggleButton(discord.ui.DynamicItem[discord.ui.Button],
                   template=rf"monke:tog:(?P<game>{_GAME}):(?P<kind>day|night):(?P<token>\w+):(?P<ability>[a-z_]+)"):
    def __init__(self, game, kind, token, ability, label="Toggle"):
        self.game, self.kind, self.token, self.ability = game, kind, token, ability
        super().__init__(discord.ui.Button(
            label=label, style=discord.ButtonStyle.danger,
            custom_id=f"monke:tog:{game}:{kind}:{token}:{ability}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["game"], match["kind"], match["token"], match["ability"])

    async def callback(self, interaction: discord.Interaction):
        await _submit_action(interaction, self.game, self.kind, self.token, self.ability, None, toggle=True)


class VerdictButton(discord.ui.DynamicItem[discord.ui.Button],
                    template=rf"monke:verdict:(?P<game>{_GAME}):(?P<token>\d+):(?P<v>guilty|innocent|abstain)"):
    STYLES = {"guilty": discord.ButtonStyle.danger, "innocent": discord.ButtonStyle.success,
              "abstain": discord.ButtonStyle.secondary}

    def __init__(self, game, token, verdict, label=None):
        self.game, self.token, self.verdict = game, token, verdict
        super().__init__(discord.ui.Button(
            label=label or verdict.capitalize(), style=self.STYLES[verdict],
            custom_id=f"monke:verdict:{game}:{token}:{verdict}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["game"], match["token"], match["v"])

    async def callback(self, interaction: discord.Interaction):
        found, err = _find(interaction, self.game, "verdict", self.token)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        state, slot = found
        try:
            await interaction.client.service.submit(state.guild_id, K.Verdict(slot, self.verdict))
        except Rejected as e:
            return await interaction.response.send_message(interaction.client.presenter.composer.error(e, state),
                                                           ephemeral=True)
        await interaction.response.send_message(_t(interaction, f"action.confirm.verdict.{self.verdict}", state),
                                                ephemeral=True)


# ---------------------------------------------------------------------------------------- vote panel (CMD-5)
async def _panel_vote(interaction: discord.Interaction, game_id: str, phase: str, target):
    service = interaction.client.service
    state = service.find_by_game_id(game_id)
    if state is None or state.status != C.RUNNING or state.phase != C.NOON or str(state.phase_id) != phase:
        return await interaction.response.send_message(_t(interaction, "error.stale_prompt", state), ephemeral=True)
    slot = state.slot_of_user(interaction.user.id)
    if slot is None:
        return await interaction.response.send_message(_t(interaction, "error.not_in_game", state), ephemeral=True)
    try:
        await service.submit(state.guild_id, K.Vote(slot, target))
    except Rejected as e:
        return await interaction.response.send_message(interaction.client.presenter.composer.error(e, state),
                                                       ephemeral=True)
    await interaction.response.send_message(_t(interaction, "ui.vote.recorded" if target is not None else
                                               "ui.vote.removed", state), ephemeral=True)


class PanelSelect(discord.ui.DynamicItem[discord.ui.Select],
                  template=rf"monke:panel:(?P<game>{_GAME}):(?P<phase>\d+)"):
    def __init__(self, game, phase, options=None, placeholder=""):
        self.game, self.phase = game, phase
        opts = options or [discord.SelectOption(label="-", value="-")]
        super().__init__(discord.ui.Select(custom_id=f"monke:panel:{game}:{phase}", options=opts[:25],
                                           placeholder=placeholder[:150] or None))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["game"], match["phase"])

    async def callback(self, interaction: discord.Interaction):
        raw = interaction.data["values"][0]
        await _panel_vote(interaction, self.game, self.phase, int(raw) if raw.isdigit() else None)


class PanelUnvote(discord.ui.DynamicItem[discord.ui.Button],
                  template=rf"monke:panelun:(?P<game>{_GAME}):(?P<phase>\d+)"):
    def __init__(self, game, phase, label="Unvote"):
        self.game, self.phase = game, phase
        super().__init__(discord.ui.Button(label=label, style=discord.ButtonStyle.secondary,
                                           custom_id=f"monke:panelun:{game}:{phase}"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["game"], match["phase"])

    async def callback(self, interaction: discord.Interaction):
        await _panel_vote(interaction, self.game, self.phase, None)


def panel_view(game_id: str, phase_id, names: dict, placeholder: str, unvote_label: str) -> discord.ui.View:
    """A select menu of living players and an Unvote button. `names`: slot -> label."""
    v = discord.ui.View(timeout=None)
    opts = [discord.SelectOption(label=label[:100], value=str(slot)) for slot, label in sorted(names.items())]
    v.add_item(PanelSelect(game_id, str(phase_id), opts, placeholder))
    v.add_item(PanelUnvote(game_id, str(phase_id), unvote_label))
    return v


# ---------------------------------------------------------------------------------------- will and death note (CARD-1/3/4)
class EditorModal(discord.ui.Modal):
    def __init__(self, interaction, state, slot: int, kind: str):
        comp = interaction.client.presenter.composer
        key = "will" if kind == "will" else "deathnote"
        super().__init__(title=comp.t(state, f"{key}.modal.title")[:45])
        self.kind, self.slot, self.guild_id = kind, slot, state.guild_id
        p = state.players[slot]
        from ..engine.cards import note_of
        limit = state.settings.will_max if kind == "will" else state.settings.note_max
        self.box = discord.ui.TextInput(label=comp.t(state, f"{key}.modal.label")[:45], style=discord.TextStyle.paragraph,
                                        required=False, default=(p.will if kind == "will" else note_of(p)) or None,
                                        max_length=min(limit, 4000))
        self.add_item(self.box)

    async def on_submit(self, interaction: discord.Interaction):
        service, comp = interaction.client.service, interaction.client.presenter.composer
        cmd = (K.SetWill if self.kind == "will" else K.SetDeathNote)(self.slot, self.box.value)
        try:
            await service.submit(self.guild_id, cmd)
        except Rejected as e:
            return await interaction.response.send_message(comp.error(e, service.get(self.guild_id)), ephemeral=True)
        await interaction.response.send_message(
            comp.t(service.get(self.guild_id), "will.saved" if self.kind == "will" else "deathnote.saved"), ephemeral=True)


async def open_editor(interaction: discord.Interaction, state, slot: int, kind: str) -> None:
    """Open the will / death note window for a living player (also used by /will and /deathnote)."""
    comp = interaction.client.presenter.composer
    p = state.players[slot]
    from ..engine.cards import NOTE_ABILITY
    if not p.alive:
        return await interaction.response.send_message(comp.t(state, "error.dead"), ephemeral=True)
    if kind == "will" and not state.settings.allow_wills:
        return await interaction.response.send_message(comp.t(state, "will.disabled"), ephemeral=True)
    if kind == "note" and p.role_id not in NOTE_ABILITY:
        return await interaction.response.send_message(comp.t(state, "deathnote.not_allowed"), ephemeral=True)
    if kind == "note" and not state.settings.allow_deathnotes:
        return await interaction.response.send_message(comp.t(state, "deathnote.disabled"), ephemeral=True)
    await interaction.response.send_modal(EditorModal(interaction, state, slot, kind))


class EditorButton(discord.ui.DynamicItem[discord.ui.Button],
                   template=rf"monke:(?P<kind>will|note):(?P<game>{_GAME})"):
    def __init__(self, kind: str, game: str, label: str = ""):
        self.kind, self.game = kind, game
        super().__init__(discord.ui.Button(label=label or kind.title(), custom_id=f"monke:{kind}:{game}",
                                           style=discord.ButtonStyle.secondary))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["kind"], match["game"])

    async def callback(self, interaction: discord.Interaction):
        state = interaction.client.service.find_by_game_id(self.game)
        slot = state.slot_of_user(interaction.user.id) if state is not None else None
        if state is None or slot is None:
            return await interaction.response.send_message(_t(interaction, "error.stale_prompt", state), ephemeral=True)
        await open_editor(interaction, state, slot, self.kind)


def card_view(game_id: str, kills: bool, labels: dict) -> discord.ui.View:
    """CARD-1: Edit Will, and for roles whose ability kills, Edit Death Note."""
    v = discord.ui.View(timeout=None)
    v.add_item(EditorButton("will", game_id, labels.get("will", "")))
    if kills:
        v.add_item(EditorButton("note", game_id, labels.get("note", "")))
    return v


DYNAMIC_ITEMS = (ActionSelect, ToggleButton, VerdictButton, PanelSelect, PanelUnvote, EditorButton)


def verdict_view(game_id: str, token: str, labels: dict = None) -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    for verdict in (C.GUILTY, C.INNOCENT, C.ABSTAIN):
        v.add_item(VerdictButton(game_id, token, verdict, (labels or {}).get(verdict)))
    return v


def prompt_view(payload: dict, names: dict, label: str = "", do_nothing: str = "Do nothing") -> discord.ui.View:
    """names: slot -> display label for select options. `label` and `do_nothing` come from the text system."""
    v = discord.ui.View(timeout=None)
    kind = payload["phase_kind"].lower()
    if payload["kind"] == "toggle":
        v.add_item(ToggleButton(payload["game_id"], kind, payload["token"], payload["ability_id"],
                                label=label[:80]))
    else:
        opts = [discord.SelectOption(label=do_nothing, value="none")]
        for slot in payload["options"]:
            opts.append(discord.SelectOption(label=names.get(slot, f"Player {slot}")[:100], value=str(slot)))
        v.add_item(ActionSelect(payload["game_id"], kind, payload["token"], payload["ability_id"], options=opts))
    return v
