"""Persistent components. DynamicItem custom IDs carry game_id + a freshness token + kind, so buttons
and menus survive restarts. Every click is re-validated by the engine (never trust the UI)."""
from __future__ import annotations

import re

import discord

from .. import constants as C
from ..engine import commands as K
from ..errors import Rejected

_GAME = r"[0-9a-f]+"
EXPIRED = "This prompt has expired."


def _find(interaction: discord.Interaction, game_id: str, kind: str, token: str):
    """Resolve (state, slot) or return (None, message)."""
    service = interaction.client.service
    state = service.find_by_game_id(game_id)
    if state is None or state.status != C.RUNNING:
        return None, EXPIRED
    if kind == "verdict":
        if state.phase != C.TRIAL_VERDICT or str(state.phase_id) != token:
            return None, EXPIRED
    elif state.token_for(kind.upper()) != token:
        return None, EXPIRED
    slot = state.slot_of_user(interaction.user.id)
    if slot is None:
        return None, "You are not in this game."
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
        return await interaction.response.send_message(e.reason, ephemeral=True)
    if toggle:
        choice = "ON" if active else "OFF"
    elif target is None:
        choice = "do nothing"
    else:
        choice = interaction.client.presenter.name_of(state, target)
    base = (interaction.message.content or "").split("\n\nCurrent choice:")[0]
    await interaction.response.edit_message(content=f"{base}\n\nCurrent choice: **{choice}**")


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

    def __init__(self, game, token, verdict):
        self.game, self.token, self.verdict = game, token, verdict
        super().__init__(discord.ui.Button(
            label=verdict.capitalize(), style=self.STYLES[verdict],
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
            return await interaction.response.send_message(e.reason, ephemeral=True)
        await interaction.response.send_message(f"Your verdict: **{self.verdict}** (you can change it until time runs out).",
                                                ephemeral=True)


DYNAMIC_ITEMS = (ActionSelect, ToggleButton, VerdictButton)


def verdict_view(game_id: str, token: str) -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    for verdict in (C.GUILTY, C.INNOCENT, C.ABSTAIN):
        v.add_item(VerdictButton(game_id, token, verdict))
    return v


def prompt_view(payload: dict, names: dict) -> discord.ui.View:
    """names: slot -> display label for select options."""
    v = discord.ui.View(timeout=None)
    kind = payload["phase_kind"].lower()
    if payload["kind"] == "toggle":
        v.add_item(ToggleButton(payload["game_id"], kind, payload["token"], payload["ability_id"],
                                label=payload["label"][:80]))
    else:
        opts = [discord.SelectOption(label="Do nothing", value="none")]
        for slot in payload["options"]:
            opts.append(discord.SelectOption(label=names.get(slot, f"Player {slot}")[:100], value=str(slot)))
        v.add_item(ActionSelect(payload["game_id"], kind, payload["token"], payload["ability_id"], options=opts))
    return v
