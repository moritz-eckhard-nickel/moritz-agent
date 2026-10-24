# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The brain of the main process: instant answers, web search, language model and agent.

The phone worker (and later Discord and the web interface) only carry speech or text to and from
this object. One ``Runtime`` owns the database, the skill services, the search chain, the model
queue and the agent loop; ``turn`` answers one utterance of a conversation (docs/plan/02 §3, §7).
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from moritz_agent import __version__
from moritz_agent.agent.loop import AgentLoop
from moritz_agent.agent.profiles import chat_profile, phone_profile
from moritz_agent.agent.responder import AgentResponder
from moritz_agent.config.reload import ConfigManager, ReloadResult, RuntimeConfig
from moritz_agent.config.settings import REPO_ROOT
from moritz_agent.core.callback import CallbackQueue
from moritz_agent.core.chat import ChatService
from moritz_agent.core.principal import discord_role, owner_ids
from moritz_agent.core.scheduler import Scheduler
from moritz_agent.core.turn import Turn, TurnResult
from moritz_agent.inference import InferenceClient, InferenceQueue, Priority
from moritz_agent.inference.process import InferenceService, koboldcpp_built
from moritz_agent.logging_setup import get_logger
from moritz_agent.phone.responder import Reply, ResponderUnavailable, TurnContext
from moritz_agent.research.fallbacks import KoboldWebSearch, WikipediaSearch
from moritz_agent.research.search import SearchBackend, SearchService
from moritz_agent.research.searxng_process import SearxngService
from moritz_agent.research.searxng_process import installed as searxng_installed
from moritz_agent.skills.clock import Clock, SystemClock
from moritz_agent.skills.providers import Providers
from moritz_agent.skills.responder import SkillResponder
from moritz_agent.skills.services import build_services
from moritz_agent.skills.tools import skill_tools
from moritz_agent.storage import Database, DiscordStore, Repo
from moritz_agent.tools.registry import ToolRegistry
from moritz_agent.tools.time_tool import GetCurrentTime
from moritz_agent.tools.web_search import WebSearch

log = get_logger("system")

CALL_END_GRACE_S = 300.0  # a call without an end notice counts as over this long after the limit


@dataclass
class Component:
    """State of one part of the system as the status page shows it."""

    state: str  # starting | ready | degraded | failed | disabled
    message: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"state": self.state, "message": self.message}
        if self.detail:
            data["detail"] = self.detail
        return data


@dataclass
class _Conversation:
    context: TurnContext
    touched: float
    task: asyncio.Task[Reply] | None = None


class _NoModel:
    """What answers when no instant answer fits and the language model cannot (yet)."""

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime

    async def respond(self, text: str, context: TurnContext) -> Reply:
        component = self.runtime.component("inference")
        if component.state == "starting":
            return Reply(prompt="starting_up")
        if component.state == "disabled":
            return Reply(
                text="Dazu kann ich gerade nichts sagen, weil mein Sprachmodell nicht eingeschaltet ist."
            )
        raise ResponderUnavailable(component.message or "language model unavailable")


class _ModelOrNot:
    """The agent when the model is ready, otherwise the honest fallback."""

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self.fallback = _NoModel(runtime)

    async def respond(self, text: str, context: TurnContext) -> Reply:
        agent = self.runtime.agent_for(context)
        if agent is None or self.runtime.component("inference").state != "ready":
            return await self.fallback.respond(text, context)
        return await agent.respond(text, context)


class Runtime:
    def __init__(
        self,
        config: ConfigManager,
        root: Path = REPO_ROOT,
        *,
        clock: Clock | None = None,
        manage_processes: bool = True,
        inference_client: InferenceClient | None = None,
        search_backends: dict[str, SearchBackend] | None = None,
        providers_transport: httpx.AsyncBaseTransport | None = None,
        providers_cache_dir: Path | None = None,
    ) -> None:
        self.config = config
        self.root = root
        self.clock: Clock = clock or SystemClock()
        self.manage_processes = manage_processes
        self._injected_client = inference_client
        self._injected_backends = search_backends
        self._providers_transport = providers_transport
        self._providers_cache_dir = providers_cache_dir
        self.started_at = time.monotonic()
        self.db: Database | None = None
        self.repo: Repo | None = None
        self.svc: Any = None
        self.skill_responder: SkillResponder | None = None
        self.agent_responder: AgentResponder | None = None
        self.agent_loop: AgentLoop | None = None
        self.registry: ToolRegistry | None = None
        self.search: SearchService | None = None
        self.queue: InferenceQueue | None = None
        self.inference: InferenceService | None = None
        self.searxng: SearxngService | None = None
        self._inference_note = Component("disabled", "nicht gestartet")
        self.agent_chat: AgentResponder | None = None  # Discord text and web: markdown, longer
        self.agent_voice: AgentResponder | None = (
            None  # Discord voice: like the phone, VOICE priority
        )
        self.discord_store: DiscordStore | None = None
        self.chat: ChatService = ChatService(self)
        self.callbacks = CallbackQueue()  # "Sag mir am Telefon …": calls the phone worker makes
        self.scheduler: Scheduler | None = None
        self.external_components: Callable[[], dict[str, Component]] = dict
        self._calls: dict[str, _Conversation] = {}
        self._call_topics: dict[str, list[str]] = {}
        self._call_started: dict[str, float] = {}
        self._call_remote: dict[str, str] = {}
        self._bad_since: dict[str, float] = {}
        self._scheduler_task: asyncio.Task[None] | None = None
        self._started = False

    # -- settings ---------------------------------------------------------------------------------
    @property
    def settings(self):
        return self.config.settings

    # -- life cycle ---------------------------------------------------------------------------------
    async def start(self) -> None:
        settings = self.settings
        self.db = Database(self.root / settings.storage.database)
        self.db.ensure()
        self.svc = build_services(
            settings,
            self.root,
            clock=self.clock,
            providers=lambda svc: Providers(
                svc, transport=self._providers_transport, cache_dir=self._providers_cache_dir
            ),
            database=self.db,
        )
        self.repo = self.svc.repo
        self.discord_store = DiscordStore(self.db)
        self.scheduler = Scheduler(
            self.discord_store,
            lambda: self.settings.discord,
            self.svc.now,
            ask=self.ask_skill,
            alerts=self.alerts_for,
            timezone=lambda: self.settings.general.timezone,
        )
        self.svc.secrets = dict(self.config.passwords.optional_services)
        self._build_model_side()
        self._build_agent()
        self.skill_responder = SkillResponder(self.svc, fallback=_ModelOrNot(self))
        self.config.on_change(self._on_config)
        if settings.skills.online and self.svc.providers is not None:
            self.svc.providers.start_prefetch()
        if self.manage_processes:
            if self.inference is not None:
                await self.inference.start()
            if self.searxng is not None:
                await self.searxng.start()
        if settings.discord.enabled:
            self._scheduler_task = asyncio.ensure_future(self._scheduler_loop())
        self._started = True
        log.info("Runtime bereit (Skills, Suche, Agent)")

    async def stop(self) -> None:
        if self._scheduler_task is not None:
            self._scheduler_task.cancel()
        for conversation in self._calls.values():
            if conversation.task is not None:
                conversation.task.cancel()
        for key in list(self.chat._conversations):
            self.chat.end(key)
        if self.searxng is not None and self.manage_processes:
            await self.searxng.stop()
        if self.inference is not None and self.manage_processes:
            await self.inference.stop()
        if self.queue is not None:
            await self.queue.aclose()
        if self.search is not None:
            await self.search.aclose()
        if self.svc is not None and self.svc.providers is not None:
            await self.svc.providers.aclose()
        if self.db is not None:
            self.db.close()
        self._started = False

    # -- building blocks ----------------------------------------------------------------------------
    def _build_model_side(self) -> None:
        settings = self.settings
        backends: dict[str, SearchBackend] = dict(self._injected_backends or {})
        client = self._injected_client
        if client is None and settings.inference.enabled:
            model = settings.resolve(settings.inference.model, self.root)
            if not model.is_file():
                self._inference_note = Component("disabled", "Modelldatei fehlt")
            elif self.manage_processes and not koboldcpp_built(settings, self.root):
                self._inference_note = Component(
                    "disabled", "KoboldCpp ist nicht gebaut (./test-3.sh setup)"
                )
            elif self.manage_processes:
                self.inference = InferenceService(settings, self.root)
                client = self.inference.client
        elif client is None:
            self._inference_note = Component("disabled", "in der Konfiguration ausgeschaltet")
        if client is not None:
            self.queue = InferenceQueue(
                client, preempt_wait_s=settings.inference.phone_preempt_wait_s
            )
            if "koboldcpp" not in backends and settings.inference.websearch_fallback:
                backends["koboldcpp"] = KoboldWebSearch(client)
        if (
            "searxng" not in backends
            and self.manage_processes
            and searxng_installed(settings, self.root)
        ):
            self.searxng = SearxngService(settings, self.root)
            backends["searxng"] = self.searxng.client
        backends.setdefault("wikipedia", WikipediaSearch())
        self.search = SearchService(settings.search, backends)

    def _build_agent(self) -> None:
        settings = self.settings
        assert self.svc is not None
        registry = ToolRegistry(repo=self.repo)
        registry.register(GetCurrentTime(settings.general.timezone, clock=self.svc.now))
        if self.search is not None:
            registry.register(WebSearch(self.search))
        from moritz_agent.skills.router import Router

        registry.register_all(skill_tools(Router(self.svc)))
        self.registry = registry
        if self.queue is None:
            self.agent_loop = self.agent_responder = None
            self.agent_chat = self.agent_voice = None
            return
        size = settings.inference.context_size
        self.agent_loop = AgentLoop(
            self.queue, registry, phone_profile(settings, self.root), context_size=size
        )
        self.agent_responder = AgentResponder(self.agent_loop)
        self.agent_voice = AgentResponder(
            AgentLoop(
                self.queue,
                registry,
                phone_profile(settings, self.root),
                context_size=size,
                priority=Priority.VOICE,
                label="discord_voice",
            )
        )
        self.agent_chat = AgentResponder(
            AgentLoop(
                self.queue,
                registry,
                chat_profile(settings, self.root),
                context_size=size,
                priority=Priority.INTERACTIVE,
                label="chat",
            )
        )

    def agent_for(self, context: TurnContext) -> AgentResponder | None:
        """The agent loop that fits the conversation: phone, Discord voice or chat."""
        if context.extras.get("surface") == "chat":
            return self.agent_chat
        if context.extras.get("channel") == "discord":
            return self.agent_voice
        return self.agent_responder

    async def _on_config(
        self, old: RuntimeConfig, new: RuntimeConfig, result: ReloadResult
    ) -> None:
        """Apply a reloaded configuration to the parts that can change while running."""
        if self.svc is None:
            return
        self.svc.settings = new.settings
        self.svc.secrets = dict(new.passwords.optional_services)
        if self.svc.providers is not None:
            self.svc.providers.refresh_config()
            if new.settings.skills.online:
                self.svc.providers.start_prefetch()
        if self.search is not None:
            self.search.configure(new.settings.search)
        if self.queue is not None:
            self._build_agent()
        if self.repo is not None:
            self.repo.store_transcripts = new.settings.storage.store_transcripts

    # -- component state -----------------------------------------------------------------------------
    def component(self, name: str) -> Component:
        return self.components()[name]

    def components(self) -> dict[str, Component]:
        found: dict[str, Component] = {"storage": self._storage_state()}
        found["inference"] = self._inference_state()
        found["search"] = self._search_state()
        found["skills"] = self._skills_state()
        found["config"] = (
            Component("degraded", f"letztes Neuladen abgelehnt: {self.config.last_error}")
            if self.config.last_error
            else Component("ready", f"Stand {self.config.current.generation}")
        )
        found.update(self.external_components())
        found["agent"] = (
            Component("ready", f"{len(self.agent_loop.profile.tools)} Werkzeuge")
            if self.agent_loop is not None and found["inference"].state == "ready"
            else Component("disabled", "ohne Sprachmodell nur Sofortauskünfte")
        )
        return found

    def _storage_state(self) -> Component:
        if self.db is None:
            return Component("starting")
        try:
            version = self.db.current_version()
        except Exception as exc:
            return Component("failed", f"Datenbank nicht lesbar ({type(exc).__name__})")
        return Component("ready", f"Schema {version}")

    def _inference_state(self) -> Component:
        if self.inference is not None:
            status = self.inference.process.status()
            states = {
                "ready": "ready",
                "starting": "starting",
                "stopping": "starting",
                "failed": "failed",
                "stopped": "starting",
            }
            return Component(
                states.get(status.state, "starting"),
                status.message or f"KoboldCpp {status.state}",
                {"restarts": status.restarts},
            )
        if self.queue is not None:
            return Component("ready", "Modellserver angebunden", {"queue": self.queue.depth()})
        return self._inference_note

    def _search_state(self) -> Component:
        if not self.settings.search.enabled:
            return Component("disabled", "Websuche ausgeschaltet")
        if self.searxng is not None:
            status = self.searxng.process.status()
            if status.state == "ready":
                return Component("ready", "SearXNG läuft")
            return Component(
                "degraded",
                f"SearXNG {status.state}, Rückfall: KoboldCpp-Websuche und Wikipedia",
            )
        names = sorted(self.search.backends) if self.search is not None else []
        return Component(
            "degraded", "SearXNG nicht eingerichtet, Rückfall: " + (", ".join(names) or "keiner")
        )

    def _skills_state(self) -> Component:
        if self.svc is None or not self.settings.skills.enabled:
            return Component("disabled", "Sofortauskünfte ausgeschaltet")
        providers = self.svc.providers
        if not self.settings.skills.online:
            return Component("degraded", "ohne Netzabruf (skills.online = false)")
        detail = providers.snapshot() if providers is not None else {}
        return Component("ready", "Sofortauskünfte bereit", {"services": detail})

    def status(self) -> dict[str, Any]:
        return {
            "version": __version__,
            "uptime_s": round(time.monotonic() - self.started_at),
            "components": {name: c.as_dict() for name, c in self.components().items()},
        }

    # -- phone calls ------------------------------------------------------------------------------
    def _call(self, call_id: str) -> _Conversation:
        conversation = self._calls.get(call_id)
        if conversation is None:
            context = TurnContext(
                call_id=call_id,
                assistant_name=self.settings.phone.assistant_name,
                timezone=self.settings.general.timezone,
                started_at=time.monotonic(),
            )
            conversation = self._calls[call_id] = _Conversation(context, time.monotonic())
        conversation.touched = time.monotonic()
        return conversation

    async def turn_events(self, call_id: str, text: str) -> AsyncIterator[dict[str, Any]]:
        """One utterance of a call: ``thinking`` events while it runs, then the ``reply``."""
        conversation = self._call(call_id)
        responder = self.skill_responder
        if responder is None:
            raise ResponderUnavailable("runtime not started")
        context = conversation.context
        task = asyncio.ensure_future(responder.respond(text, context))
        conversation.task = task
        sent: str | None = None
        started = time.monotonic()
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=0.05)
                skills = context.extras.get("skills")
                prompt = getattr(skills, "thinking_prompt", None)
                if prompt and prompt != sent:
                    sent = prompt
                    yield {"type": "thinking", "prompt": prompt}
        except asyncio.CancelledError:  # the consumer went away (connection closed)
            task.cancel()
            raise
        finally:
            conversation.task = None
        if task.cancelled():  # cancelled on purpose (hang-up): nothing to say any more
            yield {"type": "cancelled"}
            return
        reply = task.result()
        context.turn += 1
        context.last_reply = reply.text or context.last_reply
        context.history.append((text, reply.text or reply.prompt or ""))
        del context.history[:-12]
        if reply.skill_id:
            self._call_topics.setdefault(call_id, []).append(reply.skill_id)
        self._forward_to_discord(call_id, reply)
        self._record_turn(call_id, context.turn, text, reply, "phone", started)
        yield {"type": "reply", "reply": reply}

    async def turn(self, call_id: str, text: str) -> Reply:
        reply: Reply | None = None
        async for event in self.turn_events(call_id, text):
            if event["type"] == "reply":
                reply = event["reply"]
        if reply is None:
            raise ResponderUnavailable("answer cancelled")
        return reply

    def _record_turn(
        self, call_id: str | None, index: int, text: str, reply: Reply, channel: str, started: float
    ) -> None:
        if self.repo is None:
            return
        try:
            self.repo.add_turn(
                call_id,
                index,
                user_text=text,
                agent_text=reply.text,
                path="skill" if reply.skill_id else "agent",
                channel=channel,
                timings={"total_ms": round((time.monotonic() - started) * 1000)},
            )
        except Exception:
            log.debug("Gesprächsrunde nicht protokolliert", exc_info=True)

    def record_chat_turn(self, turn: Turn, reply: Reply, result: TurnResult) -> None:
        """Statistics of a chat turn: channel, path and time – the text only if it may be kept."""
        if self.repo is None:
            return
        try:
            self.repo.add_turn(
                None,
                0,
                user_text=turn.text,
                agent_text=reply.text,
                path="skill" if reply.skill_id else "agent",
                channel=turn.principal.channel,
                timings={"total_ms": result.ms},
            )
        except Exception:
            log.debug("Chat-Runde nicht protokolliert", exc_info=True)

    async def greeting_hint(self, call_id: str) -> str | None:
        if self.skill_responder is None:
            return None
        return await self.skill_responder.greeting_hint(self._call(call_id).context)

    def cancel(self, call_id: str) -> bool:
        """Hang-up: stop the answer in progress (the model generation is aborted with it)."""
        conversation = self._calls.get(call_id)
        if conversation is not None and conversation.task is not None:
            conversation.task.cancel()
            return True
        return False

    def _forward_to_discord(self, call_id: str, reply: Reply) -> None:
        """ "Schick mir das auf Discord": the caller's extension → Discord id (``discord.phone_extensions``),
        otherwise the owner (docs/plan/14 §12). A direct message, delivered by the Discord worker."""
        forward = getattr(reply.result, "forward", None)
        store, cfg = self.discord_store, self.settings.discord
        if forward is None or store is None or not cfg.enabled:
            return
        match = re.search(r"sip:([^@;>]+)", self._call_remote.get(call_id, ""))
        user = cfg.phone_extensions.get(match.group(1)) if match else None
        user = user or next(iter(owner_ids(cfg)), None)
        if user is None:
            return
        title, text = forward
        store.enqueue("forward", f"dm:{user}", {"title": title, "text": text}, user_id=user)

    def call_started(self, call_id: str, remote: str = "", codec: str = "") -> None:
        self._call_remote[call_id] = remote
        self._call(call_id)
        self._call_started[call_id] = time.monotonic()
        if self.repo is not None:
            with contextlib.suppress(Exception):
                self.repo.start_call(call_id, remote, codec)

    def callback_done(self, callback_id: int, outcome: str) -> None:
        """The phone worker tried to call back. Nobody picked up: then nobody picked up (Moritz).

        Only when the PBX refuses the call at all, the owners get a system note – otherwise they
        would never learn why the phone stays silent."""
        call = self.callbacks.done(callback_id)
        log.info("Rückruf %d: %s", callback_id, outcome)
        if outcome == "forbidden" and call is not None and self.scheduler is not None:
            self.scheduler.system_event(
                "callback_forbidden",
                f"Ich darf die {call.extension} nicht anrufen – die Telefonanlage lehnt ab. Im Dialplan "
                f"[from-agent] die {call.extension} erlauben (Anleitung: docs/asterisk-konfiguration.md).",
            )

    def call_ended(self, call_id: str, reason: str = "") -> None:
        conversation = self._calls.pop(call_id, None)
        self._call_remote.pop(call_id, None)
        if conversation is not None and conversation.task is not None:
            conversation.task.cancel()
        topics = self._call_topics.pop(call_id, [])
        started = self._call_started.pop(call_id, None)
        if self.repo is not None:
            turns = conversation.context.turn if conversation else 0
            with contextlib.suppress(Exception):
                self.repo.end_call(call_id, reason or "ended", turns)
        if self.scheduler is not None and self.settings.discord.enabled:
            seconds = round(time.monotonic() - started) if started is not None else 0
            self.scheduler.call_event(self._call_summary(conversation, topics, seconds))

    def _call_summary(
        self, conversation: _Conversation | None, topics: list[str], seconds: int
    ) -> str:
        """ "Anruf, 3 Min. 12 s" – with topics or transcript only if allowed (docs/plan/14 §12)."""
        minutes, rest = divmod(seconds, 60)
        text = f"Anruf beendet, {minutes} Min. {rest} s"
        mode = self.settings.discord.call_summaries
        if mode == "topics" and topics:
            groups = sorted({topic.split(".")[0] for topic in topics})
            text += ". Themen: " + ", ".join(groups)
        elif mode == "transcript" and conversation is not None:
            lines = [f"Du: {heard}\nAnton: {said}" for heard, said in conversation.context.history]
            text += ".\n" + "\n".join(lines)
        return text

    @property
    def active_calls(self) -> int:
        self._expire_calls()
        return len(self._calls)

    def _expire_calls(self) -> None:
        """A call whose end never arrived (phone worker crashed or restarted mid-call) must not
        count as active forever: no call outlives ``max_call_duration_s``."""
        limit = self.settings.phone.max_call_duration_s + CALL_END_GRACE_S
        now = time.monotonic()
        for call_id, conversation in list(self._calls.items()):
            if now - conversation.touched > limit:
                log.warning("Anruf %s ohne Ende-Meldung – gilt als beendet", call_id)
                self.call_ended(call_id, "abgelaufen")

    @property
    def generating(self) -> bool:
        return bool(self.queue and self.queue.busy)

    # -- helpers of the scheduler -------------------------------------------------------------------------
    def _discord_principal(self, user_id: str):
        return self.chat.principal(user_id, discord_role(self.settings.discord, user_id))

    async def ask_skill(self, user_id: str, text: str):
        """Run the skills as ``user_id`` (their home town) – for briefings and hints."""
        from moritz_agent.skills.router import new_context

        assert self.skill_responder is not None
        principal = self._discord_principal(user_id)
        ctx = new_context(self.svc)
        ctx.role, ctx.user_id = principal.role.value, user_id
        ctx.home = self.chat.home_of(principal)
        return await self.skill_responder.router.route(text, ctx, surface="chat")

    async def alerts_for(self, user_id: str):
        from moritz_agent.skills.slots.where import home_place

        providers = self.svc.providers
        if providers is None:
            return []
        ctx = self.svc.skill_ctx_stub if hasattr(self.svc, "skill_ctx_stub") else None
        principal = self._discord_principal(user_id)
        place = self.chat.home_of(principal) or home_place(self.svc, ctx)
        fetched = await providers.alerts(place)
        return fetched.data

    async def _scheduler_loop(self) -> None:
        """Every ten seconds: due reminders, warnings, briefings; once a minute: component watch."""
        assert self.scheduler is not None
        beat = 0
        for owner in self.settings.discord.owner_user_ids:
            self.scheduler.ensure_defaults(owner)
        while True:
            await asyncio.sleep(10)
            try:
                await self.scheduler.tick()
                beat += 1
                if beat % 6 == 0:
                    self.watch_components()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Planer fehlgeschlagen")

    def watch_components(self, now: float | None = None) -> None:
        """A note for the owners when a part is down for more than five minutes (once an hour)."""
        if self.scheduler is None:
            return
        now = time.monotonic() if now is None else now
        names = {
            "phone": "Das Telefon",
            "inference": "Das Sprachmodell",
            "storage": "Die Datenbank",
        }
        for name, label in names.items():
            component = self.components().get(name)
            if component is None or component.state not in {"failed"}:
                self._bad_since.pop(name, None)
                continue
            since = self._bad_since.setdefault(name, now)
            if now - since >= 300:
                self.scheduler.system_event(name, f"{label} ist seit mehr als 5 Minuten gestört.")

    # -- background jobs ----------------------------------------------------------------------------
    def purge(self) -> dict[str, int]:
        """Retention (STORE-01): old transcripts and missed questions go."""
        if self.repo is None:
            return {}
        return self.repo.purge(self.settings.storage.transcript_retention_hours)

    # -- for the Discord worker ----------------------------------------------------------------------------
    async def situation(self) -> dict[str, Any]:
        """What the activities react to (docs/plan/14 §8.5): call, maintenance, weather, warnings."""
        from moritz_agent.skills.slots.where import home_place

        data: dict[str, Any] = {
            "call": self.active_calls > 0,
            "weather": None,
            "temperature": None,
            "warning_level": 0,
            "services_down": not self.settings.skills.online,
        }
        providers = self.svc.providers if self.svc else None
        if providers is None or not self.settings.skills.online:
            return data
        home = home_place(self.svc)
        try:
            fetched = await asyncio.wait_for(providers.weather(home, need="current"), 0.6)
            current = fetched.data.current
            data["temperature"] = current.temperature if current else None
            data["weather"] = _weather_kind(current.code if current else None, data["temperature"])
        except Exception:
            data["services_down"] = True
        warnings = providers.cached_alerts(home) or []
        now = self.svc.now()
        data["warning_level"] = max(
            (w.level for w in warnings if w.end is None or w.end > now), default=0
        )
        return data

    def recent_calls(self, limit: int = 10) -> list[dict[str, Any]]:
        """Time, length and end of the latest calls – never their content (docs/plan/14 §12)."""
        if self.db is None:
            return []
        rows = self.db.query(
            "SELECT started_at, ended_at, remote_uri, end_reason, turns FROM calls "
            "ORDER BY started_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]


def _weather_kind(code: int | None, temperature: float | None) -> str | None:
    """WMO weather code → rain | snow | thunder | hot | None (for the activities)."""
    if code is not None:
        if code >= 95:
            return "thunder"
        if code in {71, 73, 75, 77, 85, 86}:
            return "snow"
        if code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}:
            return "rain"
    if temperature is not None and temperature >= 30:
        return "hot"
    return None
