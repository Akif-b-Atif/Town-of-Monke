"""Turns the registry into running commands: slash registration, `monke` prefix messages, access checks, confirmations
and error replies (CMD-1, CMD-3, CMD-4, CMD-6). Nothing here knows what a command does."""
from __future__ import annotations

import inspect
import logging
from typing import Optional

import discord
from discord import app_commands

from ..errors import Rejected
from . import info
from .confirm import ConfirmView
from .ctx import Ctx
from .registry import CommandSpec, find, parse_args, split_prefix

log = logging.getLogger("monke.dispatch")
_PY = {"player": str, "text": str, "rest": str, "int": int, "bool": bool, "member": discord.Member}
_ADMIN = ("admin", "admin_any")


class Dispatcher:
    def __init__(self, bot, specs: list):
        self.bot, self.specs = bot, specs

    # ------------------------------------------------------------------ text
    def _t(self, key: str, **vars) -> str:
        return self.bot.presenter.composer.t(None, key, **vars)

    # ------------------------------------------------------------------ access (CMD-1: generated from `who`)
    async def access(self, spec: CommandSpec, ctx: Ctx) -> None:
        if ctx.guild is None:
            raise Rejected("error.no_game")
        if spec.who == "player":
            g = self.bot.service.get(ctx.guild_id)
            slot = g.slot_of_user(ctx.user.id) if g is not None else None
            if g is None or slot is None:
                raise Rejected("error.not_in_game")
            if spec.alive_only and not g.players[slot].alive:
                raise Rejected("error.dead")
            ctx.state, ctx.slot = g, slot
            return
        if spec.who == "manage_server":
            if not ctx.user.guild_permissions.manage_guild:
                raise Rejected("error.not_admin")
            return
        cfg = await self.bot.store.get_config(ctx.guild_id)
        if cfg is None:
            raise Rejected("error.not_set_up")
        is_admin = any(r.id == cfg.admin_role_id for r in ctx.user.roles)  # ADM-3: the live role, every time
        if spec.who == "admin_any":  # ADM-6: Monke Admin holders or Manage Server, in any channel
            if not (is_admin or ctx.user.guild_permissions.manage_guild):
                raise Rejected("error.not_admin")
            return
        if not is_admin:
            raise Rejected("error.not_admin")
        if ctx.channel.id != cfg.commands_channel_id:  # CMD-4: admin commands work only in Monke Commands
            raise Rejected("error.wrong_channel")
        ctx.state = self.bot.service.get(ctx.guild_id)

    # ------------------------------------------------------------------ running
    async def execute(self, spec: CommandSpec, ctx: Ctx, args: dict) -> None:
        try:
            await self.access(spec, ctx)
            if spec.confirm is not None:
                question = await spec.confirm(self.bot, ctx, **{k: v for k, v in args.items() if k in _params(spec.confirm)})
                if question is not None:
                    return await self.ask(spec, ctx, args, question)
            await spec.handler(self.bot, ctx, **args)
        except Rejected as e:
            if ctx.interaction is None and e.key in ("error.not_admin", "error.wrong_channel", "error.not_set_up",
                                                     "error.not_in_game"):
                return  # a prefix message from someone who cannot use it: the bot stays quiet, as it always has
            await self._fail(spec, ctx, ctx.err(e))
        except Exception:
            log.exception("command %s failed", spec.name)
            await self._fail(spec, ctx, self._t("error.generic"))

    async def _fail(self, spec: CommandSpec, ctx: Ctx, text: str) -> None:
        try:
            if spec.who in _ADMIN or spec.who == "manage_server":
                await ctx.say(text, ephemeral=True)
            else:
                await ctx.reply(text, ephemeral=True)  # CMD-6: every error is ephemeral
        except discord.HTTPException:
            log.exception("could not report an error")

    async def ask(self, spec: CommandSpec, ctx: Ctx, args: dict, question: tuple) -> None:
        """CMD-3: a Confirm / Cancel prompt any Monke Admin may press, expiring after 60 s."""
        key, vars = question
        c = self.bot.presenter.composer

        async def confirmed(interaction: discord.Interaction) -> None:
            pressed = Ctx(self.bot, ctx.guild, interaction.channel, interaction.user, interaction=interaction)
            pressed.state = self.bot.service.get(ctx.guild_id)
            try:
                await spec.handler(self.bot, pressed, **args)
            except Rejected as e:
                await pressed.reply(pressed.err(e), ephemeral=True)
            except Exception:
                log.exception("confirmed command %s failed", spec.name)
                await pressed.reply(self._t("error.generic"), ephemeral=True)

        view = ConfirmView(self.bot, ctx.guild_id, confirmed,
                           {"confirm": c.t(None, "ui.button.confirm"), "cancel": c.t(None, "ui.button.cancel")},
                           c.t(None, "confirm.expired"), c.t(None, "confirm.cancelled"))
        view.message = await ctx.reply(f"**{ctx.name()}**: {c.t(ctx.state, key, **vars)}", view=view)

    # ------------------------------------------------------------------ prefix: `monke <command> ...` (admin forms)
    async def on_message(self, message: discord.Message) -> bool:
        if message.guild is None:
            return False
        parsed = split_prefix(message.content)
        if parsed is None:
            return False
        spec = find([s for s in self.specs if s.prefix], parsed[0])
        if spec is None:
            return False
        ctx = Ctx(self.bot, message.guild, message.channel, message.author, message=message)
        try:
            args = parse_args(spec, parsed[1])
        except Rejected as e:
            await self._fail(spec, ctx, ctx.err(e))
            return True
        await self.execute(spec, ctx, args)
        return True

    # ------------------------------------------------------------------ slash
    def slash_commands(self) -> list:
        return [self._make_slash(s) for s in self.specs]

    def _make_slash(self, spec: CommandSpec) -> app_commands.Command:
        c = self.bot.presenter.composer
        arg_specs = spec.slash_args if spec.slash_args is not None else spec.args
        arg_specs = tuple(a for a in arg_specs if a.kind != "rest") or ()
        params = [inspect.Parameter("interaction", inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                    annotation=discord.Interaction)]
        annotations = {"interaction": discord.Interaction}
        for a in sorted(arg_specs, key=lambda x: not x.required):  # required options first
            py = _PY[a.kind]
            ann = py if a.required else Optional[py]
            annotations[a.name] = ann
            params.append(inspect.Parameter(a.name, inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                            default=inspect.Parameter.empty if a.required else None, annotation=ann))
        dispatcher = self

        async def callback(interaction: discord.Interaction, **kw):
            await dispatcher.run_slash(spec, interaction, kw)

        callback.__signature__ = inspect.Signature(params)
        callback.__annotations__ = annotations
        callback.__name__ = f"cmd_{spec.name}"
        callback.__discord_app_commands_guild_only__ = True
        callback.__discord_app_commands_param_description__ = {
            a.name: c.t(None, f"help.arg.{a.name}")[:100] for a in arg_specs}
        cmd = app_commands.Command(name=spec.name, description=c.t(None, spec.help_key)[:100], callback=callback)
        for a in arg_specs:
            if a.kind == "player":
                cmd.autocomplete(a.name)(self._autocomplete)
        return cmd

    async def run_slash(self, spec: CommandSpec, interaction: discord.Interaction, kw: dict) -> None:
        ctx = Ctx(self.bot, interaction.guild, interaction.channel, interaction.user, interaction=interaction)
        args = {k: v for k, v in kw.items() if v is not None}
        if spec.join is not None:
            args = spec.join(args)
        else:
            args = {**spec.defaults, **args}
        for a in spec.args:  # members arrive as objects; handlers take ids
            if a.kind == "member" and a.name in args and hasattr(args[a.name], "id"):
                args[a.name] = args[a.name].id
        await self.execute(spec, ctx, args)

    async def _autocomplete(self, interaction: discord.Interaction, current: str):
        """QOL-6: living players except yourself and anyone pardoned today, by name or slot, labelled 'Maya (#3)'."""
        g = self.bot.service.get(interaction.guild_id) if interaction.guild_id else None
        slot = g.slot_of_user(interaction.user.id) if g is not None else None
        if g is None or slot is None:
            return []
        return [app_commands.Choice(name=label, value=str(s)) for s, label in info.vote_targets(g, slot, current)]


def _params(fn) -> set:
    return set(inspect.signature(fn).parameters) - {"bot", "ctx"}
