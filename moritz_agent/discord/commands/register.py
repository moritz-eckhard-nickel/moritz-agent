# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The command table as discord.py commands (docs/plan/14 §7): registration, options, autocomplete.

Only the functions that are active are registered. The tree is compared with the stored fingerprint
and sent to Discord only when it changed (``python -m moritz_agent.discord sync-commands`` forces it).
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any, Optional

import discord
from discord import app_commands

from moritz_agent.discord.commands import spec as commands

Bridge = Callable[[discord.Interaction, commands.Spec, dict[str, Any]], Awaitable[None]]
MenuBridge = Callable[[discord.Interaction, str, discord.Message], Awaitable[None]]
Suggest = Callable[[discord.Interaction, str], Awaitable[list[app_commands.Choice[str]]]]


def contexts(
    spec: commands.Spec,
) -> tuple[app_commands.AppCommandContext, app_commands.AppInstallationType]:
    """Where a command shows up: server, direct message, anywhere (user app)."""
    where = spec.rule.contexts.split()
    return (
        app_commands.AppCommandContext(
            guild="S" in where or "U" in where,
            dm_channel="DM" in where,
            private_channel="U" in where,
        ),
        app_commands.AppInstallationType(guild=True, user="U" in where),
    )


def _annotation(opt: commands.Opt) -> Any:
    if opt.kind == "int":
        if opt.low is not None or opt.high is not None:
            return app_commands.Range[int, opt.low, opt.high]
        return int
    if opt.kind == "channel":
        return discord.VoiceChannel
    return str


def _callback(spec: commands.Spec, bridge: Bridge) -> Callable[..., Awaitable[None]]:
    async def callback(interaction: discord.Interaction, **values: Any) -> None:
        await bridge(interaction, spec, values)

    ordered = sorted(spec.options, key=lambda o: not o.required)  # required options come first
    params = [
        inspect.Parameter(
            "interaction", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=discord.Interaction
        )
    ]
    for opt in ordered:
        annotation = _annotation(opt)
        params.append(
            inspect.Parameter(
                opt.name,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=inspect.Parameter.empty if opt.required else None,
                annotation=annotation if opt.required else Optional[annotation],  # noqa: UP045
            )
        )
    callback.__signature__ = inspect.Signature(params)  # type: ignore[attr-defined]
    callback.__name__ = f"command_{spec.name}".replace("-", "_")
    if spec.options:
        app_commands.describe(**{o.name: o.description for o in spec.options})(callback)
    choices = {
        o.name: [app_commands.Choice(name=label, value=value) for label, value in o.choices]
        for o in spec.options
        if o.choices
    }
    if choices:
        app_commands.choices(**choices)(callback)
    return callback


def command_for(
    spec: commands.Spec, bridge: Bridge, suggest: Suggest | None = None
) -> app_commands.Command[Any, ..., Any]:
    allowed_contexts, allowed_installs = contexts(spec)
    command = app_commands.Command(
        name=spec.name,
        description=spec.description,
        callback=_callback(spec, bridge),
        allowed_contexts=allowed_contexts,
        allowed_installs=allowed_installs,
    )
    if suggest is not None:
        for opt in spec.options:
            if opt.autocomplete == "place":
                command.autocomplete(opt.name)(suggest)
    return command


def build(
    tree: app_commands.CommandTree,
    features: commands.Features,
    bridge: Bridge,
    menu_bridge: MenuBridge,
    suggest: Suggest | None = None,
) -> list[dict[str, Any]]:
    """Put the active commands into ``tree``; returns their payloads (for the fingerprint)."""
    tree.clear_commands(guild=None)
    for spec in commands.active_specs(features):
        if spec.subcommands:
            allowed_contexts, allowed_installs = contexts(spec)
            group = app_commands.Group(
                name=spec.name,
                description=spec.description,
                allowed_contexts=allowed_contexts,
                allowed_installs=allowed_installs,
            )
            for sub in spec.subcommands:
                group.add_command(command_for(sub, bridge, suggest))
            tree.add_command(group)
        else:
            tree.add_command(command_for(spec, bridge, suggest))
    for name, _, feature in commands.MENUS:
        if features.has(feature):
            tree.add_command(_menu(name, menu_bridge))
    return [c.to_dict(tree) for c in tree.get_commands()]  # slash commands and menus


def _menu(name: str, menu_bridge: MenuBridge) -> app_commands.ContextMenu:
    async def callback(interaction: discord.Interaction, message: discord.Message) -> None:
        await menu_bridge(interaction, name, message)

    return app_commands.ContextMenu(
        name=name,
        callback=callback,
        type=discord.AppCommandType.message,
        allowed_contexts=app_commands.AppCommandContext(
            guild=True, dm_channel=True, private_channel=True
        ),
        allowed_installs=app_commands.AppInstallationType(guild=True, user=True),
    )
