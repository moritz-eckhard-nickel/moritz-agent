# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Typed settings for config/moritz-agent.toml (CFG-08, ADR-012).

Every key of ``config/moritz-agent.example.toml`` has a field with the same default. Unknown
keys are rejected, so typos surface at startup instead of being silently ignored.
Credentials never live here – they are in passwords.txt (see ``secrets.py``).
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_CONFIG_NAME = "moritz-agent.toml"
EXAMPLE_CONFIG_NAME = "moritz-agent.example.toml"


class SettingsError(ValueError):
    """The settings file is missing, malformed or invalid."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class General(_Section):
    timezone: str = "Europe/Berlin"
    language: str = "de"
    data_dir: str = "data"
    models_dir: str = "models"
    passwords_file: str = "passwords.txt"
    config_poll_s: int = Field(0, ge=0)


class Server(_Section):
    host: str = "0.0.0.0"
    port: int = Field(3501, ge=1, le=65535)
    tls: bool = True
    tls_cert: str = "runtime/tls/cert.pem"
    tls_key: str = "runtime/tls/key.pem"
    session_ttl_hours: int = Field(12, ge=1)
    login_max_attempts: int = Field(5, ge=1)
    login_window_minutes: int = Field(5, ge=1)


class Logging(_Section):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    file: str = "data/logs/moritz-agent.log"
    max_bytes: int = Field(10_485_760, ge=1024)
    backup_count: int = Field(10, ge=0)
    pjsip_log_level: int = Field(3, ge=0, le=6)


class Inference(_Section):
    enabled: bool = True
    koboldcpp_script: str = "koboldcpp.py"
    python: str = ""  # leer: KoboldCpps Build-Umgebung (conda/envs/linux), sonst diese Python
    model: str = "models/llm/Qwen3-30B-A3B-Instruct-2507-UD-Q3_K_XL.gguf"
    context_size: int = Field(8192, ge=512)  # INF-05: gemessen auf Sophie-1 (24.10.2026)
    gpu_layers: int = 999
    moe_cpu_layers: int = Field(24, ge=0)
    use_cuda: bool = True
    jinja: bool = True
    flash_attention: bool = True  # --flashattention: weniger VRAM für den Kontext (ADR-016)
    chat_adapter: str = ""
    threads: int = Field(12, ge=0)
    batch_threads: int = Field(12, ge=0)
    websearch_fallback: bool = True
    startup_timeout_s: int = Field(180, ge=1)
    request_timeout_s: int = Field(60, ge=1)
    phone_preempt_wait_s: float = Field(3, ge=0)


class Search(_Section):
    enabled: bool = True
    backends: list[str] = ["searxng", "koboldcpp", "wikipedia"]
    timeout_s: float = Field(6, gt=0)
    fallback_timeout_s: float = Field(8, gt=0)
    max_results: int = Field(5, ge=1, le=20)
    language: str = "de-DE"
    safesearch: int = Field(0, ge=0, le=2)
    searxng_venv: str = "runtime/searxng-venv"
    searxng_source: str = "third_party/searxng"
    searxng_settings: str = "config/searxng/settings.yml"
    searxng_startup_timeout_s: float = Field(90, gt=0)


class Vad(_Section):
    engine: Literal["silero"] = "silero"
    model: str = "assets/models/vad/silero_vad.onnx"
    threshold: float = Field(0.5, gt=0, lt=1)
    min_silence_ms: int = Field(700, ge=100)
    speech_pad_ms: int = Field(300, ge=0)
    min_speech_ms: int = Field(250, ge=50)
    max_utterance_s: float = Field(20, gt=1)


class Stt(_Section):
    engine: Literal["faster-whisper"] = "faster-whisper"
    model: str = "models/stt/faster-whisper-small"
    compute_type: str = "int8"
    beam_size: int = Field(1, ge=1)
    cpu_threads: int = Field(8, ge=0)
    no_speech_threshold: float = 0.6
    min_avg_logprob: float = -1.0
    initial_prompt: str = "Anton, Moritz, Weilburg, Limburg, Lahn, Wetzlar, Hessen, Frankfurt, Wetter, Postleitzahl, Grad."


class PiperSettings(_Section):
    voice: str = "models/tts/piper/Thorsten-Voice_Hessisch_Piper_high-Oct2023.onnx"
    length_scale: float = Field(1.0, gt=0.3, lt=3)


class EspeakSettings(_Section):
    voice: str = "de"
    speed_wpm: int = Field(150, ge=80, le=450)


class Tts(_Section):
    engine: Literal["piper", "espeak"] = "piper"
    fallback_engines: list[Literal["piper", "espeak"]] = ["espeak"]
    cpu_threads: int = Field(4, ge=1)
    loudness_target_dbfs: float = Field(-20.0, le=-6, ge=-40)
    cache_dir: str = "assets/audio/cache"
    live_cache_entries: int = Field(64, ge=0)
    piper: PiperSettings = PiperSettings()
    espeak: EspeakSettings = EspeakSettings()


class PhoneCallback(_Section):
    """Anton calls back (Discord text: "Sag mir am Telefon, …")."""

    enabled: bool = True
    extension: str = Field("201", pattern=r"^[0-9*#+]{1,20}$")
    ring_min_s: float = Field(10.0, ge=3, le=60)
    ring_max_s: float = Field(15.0, ge=3, le=60)
    speak_after_s: float = Field(1.0, ge=0, le=10)

    @model_validator(mode="after")
    def _ring_range(self) -> PhoneCallback:
        if self.ring_max_s < self.ring_min_s:
            raise ValueError("ring_max_s darf nicht kleiner sein als ring_min_s")
        return self


class Phone(_Section):
    enabled: bool = True
    assistant_name: str = "Anton"
    greeting_text: str = "Hallo Moritz, hier ist Anton. Was kann ich für dich tun?"
    local_sip_port: int = Field(5060, ge=1, le=65535)
    rtp_port_start: int = Field(40000, ge=1024, le=65000)
    rtp_port_count: int = Field(200, ge=4, le=10000)
    codecs: list[str] = ["G722/16000", "PCMA/8000", "PCMU/8000"]
    allowed_source_ips: list[str] = ["192.168.1.176"]
    max_concurrent_calls: Literal[1] = 1
    ring_seconds_min: float = Field(4.0, ge=0, le=30)
    ring_seconds_max: float = Field(8.0, ge=0, le=30)
    register_retry_min_s: int = Field(5, ge=1)
    register_retry_max_s: int = Field(300, ge=1)
    silence_prompt_s: float = Field(10, gt=0)
    silence_hangup_s: float = Field(10, gt=0)
    thinking_prompt_after_s: float = Field(2.5, gt=0)
    turn_deadline_s: float = Field(15, gt=0)
    max_reprompts: int = Field(2, ge=0)
    max_unclear_hangup: int = Field(4, ge=1)
    max_call_duration_s: float = Field(1800, gt=10)
    playback_tail_guard_ms: int = Field(300, ge=0)
    media_dead_timeout_s: float = Field(20, gt=1)
    vad: Vad = Vad()
    stt: Stt = Stt()
    tts: Tts = Tts()
    callback: PhoneCallback = PhoneCallback()

    @model_validator(mode="after")
    def _ring_range(self) -> Phone:
        if self.ring_seconds_max < self.ring_seconds_min:
            raise ValueError("ring_seconds_max darf nicht kleiner sein als ring_seconds_min")
        return self

    @field_validator("codecs")
    @classmethod
    def _codecs_known(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("at least one codec is required")
        for codec in value:
            if "/" not in codec:
                raise ValueError(f"codec '{codec}' must look like NAME/RATE, e.g. PCMA/8000")
        return value


class AgentPhone(_Section):
    max_tool_steps: int = Field(3, ge=1)
    max_answer_tokens: int = Field(160, ge=16)
    temperature: float = Field(0.3, ge=0, le=2)
    deadline_s: float = Field(15, gt=0)
    max_sentences: int = Field(3, ge=1, le=6)
    tools: list[str] = [
        "get_current_time",
        "web_search",
        "get_weather",
        "get_warnings",
        "get_pollen",
        "get_air_quality",
        "get_sun_moon",
        "calendar_info",
        "calculate",
        "money_info",
        "regional_info",
        "place_info",
        "everyday_advice",
    ]
    system_prompt_file: str = "moritz_agent/agent/prompts/phone.de.md"


class Agent(_Section):
    phone: AgentPhone = AgentPhone()


class Storage(_Section):
    database: str = "data/moritz-agent.sqlite3"
    store_transcripts: bool = True
    transcript_retention_hours: int = Field(24, ge=1)


class Fastpaths(_Section):
    enabled: bool = True
    state: str = "HE"


class SkillsHome(_Section):
    postal_code: str = "35781"
    name: str = "Weilburg"
    state: str = "HE"
    latitude: float = Field(0.0, ge=-90, le=90)  # 0 = take it from the gazetteer
    longitude: float = Field(0.0, ge=-180, le=180)
    region_places: list[str] = ["Limburg an der Lahn", "Wetzlar"]


class SkillsTime(_Section):
    spoken_style: Literal["digital", "umgangssprachlich"] = "digital"
    quarter_dialect: bool = True


class SkillsCalendar(_Section):
    workdays: list[int] = [1, 2, 3, 4, 5]  # ISO weekdays


class SkillsWeather(_Section):
    provider: Literal["open-meteo"] = "open-meteo"
    fallback_provider: Literal["brightsky", ""] = "brightsky"
    open_meteo_url: str = "https://api.open-meteo.com"
    brightsky_url: str = "https://api.brightsky.dev"
    model: str = "best_match"
    forecast_days: int = Field(10, ge=1, le=16)
    past_days: int = Field(3, ge=0, le=7)
    coordinate_decimals: int = Field(2, ge=0, le=4)
    cache_current_minutes: int = Field(10, ge=1)
    cache_forecast_minutes: int = Field(30, ge=1)
    max_stale_hours: int = Field(6, ge=0)
    prefetch_home: bool = True
    prefetch_interval_minutes: int = Field(30, ge=5)
    mention_source: Literal["always", "first", "on_request"] = "on_request"


class SkillsWarnings(_Section):
    enabled: bool = True
    sources: list[Literal["dwd", "nina"]] = ["dwd", "nina"]
    announce_on_greeting: Literal["off", "moderate", "severe", "extreme"] = "severe"
    refresh_minutes: int = Field(10, ge=1)
    nina_ars: str = Field("065330000000", pattern=r"^(\d{12})?$")  # district key for NINA, "" = off


class SkillsPollen(_Section):
    enabled: bool = True
    dwd_partregion: str = "Nordhessen und hessische Mittelgebirge"
    allergens: list[str] = []


class SkillsToggle(_Section):
    enabled: bool = True


class SkillsWater(_Section):
    enabled: bool = True
    river: str = "LAHN"
    station: str = "auto"


class SkillsWaste(_Section):
    enabled: bool = False
    ics_url: str = ""
    ics_file: str = ""


class SkillsMoney(_Section):
    currency: bool = True
    electricity: bool = True
    bidding_zone: str = "DE-LU"
    fuel: bool = False
    fuel_type: Literal["e5", "e10", "diesel"] = "e10"
    fuel_radius_km: float = Field(5, gt=0, le=25)


class SkillsFootball(_Section):
    enabled: bool = False
    team: str = "Eintracht Frankfurt"
    league: str = "bl1"


class SkillsNews(_Section):
    enabled: bool = False
    max_headlines: int = Field(3, ge=1, le=10)


class SkillsNotes(_Section):
    enabled: bool = False
    retention_days: int = Field(30, ge=1)


class SkillsSpelling(_Section):
    alphabet: Literal["din5009", "traditionell"] = "din5009"


class SkillsTimer(_Section):
    enabled: bool = True
    max_minutes: int = Field(15, ge=1, le=180)


class Skills(_Section):
    """Instant answers without the language model (docs/plan/13-sofortauskuenfte.md)."""

    enabled: bool = True
    disabled: list[str] = []
    online: bool = True
    http_connect_timeout_s: float = Field(1.5, gt=0)
    http_timeout_s: float = Field(3.0, gt=0)
    cache_dir: str = "data/cache/skills"
    max_sentences: int = Field(3, ge=1, le=6)
    answer_variation: bool = True
    store_misses: bool = True
    home: SkillsHome = SkillsHome()
    time: SkillsTime = SkillsTime()
    calendar: SkillsCalendar = SkillsCalendar()
    weather: SkillsWeather = SkillsWeather()
    warnings: SkillsWarnings = SkillsWarnings()
    pollen: SkillsPollen = SkillsPollen()
    air: SkillsToggle = SkillsToggle()
    advice: SkillsToggle = SkillsToggle()
    water: SkillsWater = SkillsWater()
    waste: SkillsWaste = SkillsWaste()
    money: SkillsMoney = SkillsMoney()
    football: SkillsFootball = SkillsFootball()
    news: SkillsNews = SkillsNews()
    notes: SkillsNotes = SkillsNotes()
    spelling: SkillsSpelling = SkillsSpelling()
    fun: SkillsToggle = SkillsToggle()
    timer: SkillsTimer = SkillsTimer()

    @field_validator("calendar", mode="after")
    @classmethod
    def _workdays_valid(cls, value: SkillsCalendar) -> SkillsCalendar:
        if not value.workdays or any(day < 1 or day > 7 for day in value.workdays):
            raise ValueError("workdays must be ISO weekdays 1 (Monday) … 7 (Sunday)")
        return value


class Sandbox(_Section):
    connect_timeout_s: int = Field(10, ge=1)


def _ids(value: object) -> object:
    """Discord ids are numbers too big for some tools: accept numbers, always keep text."""
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}
    return value


_TIME_RANGE = r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$"
IdList = Annotated[list[str], BeforeValidator(_ids)]


class DiscordRateLimits(_Section):
    owner_per_minute: int = Field(30, ge=1)
    trusted_per_minute: int = Field(10, ge=1)
    guest_per_minute: int = Field(3, ge=1)


class DiscordActivities(_Section):
    enabled: bool = True
    rotate_minutes: list[int] = [7, 15]
    situational: bool = True
    night: str = Field("23:00-06:00", pattern=_TIME_RANGE)

    @field_validator("rotate_minutes")
    @classmethod
    def _range(cls, value: list[int]) -> list[int]:
        if len(value) != 2 or value[0] < 5 or value[1] < value[0]:
            raise ValueError("rotate_minutes: [von, bis] mit mindestens 5 Minuten")
        return value


class DiscordVoice(_Section):
    enabled: bool = True
    default_channel_id: str = ""
    auto_join: bool = False
    greeting: Literal["phone"] = "phone"
    after_goodbye: Literal["leave", "stay"] = "leave"
    on_silence: Literal["rest", "leave"] = "rest"
    idle_leave_minutes: int = Field(10, ge=1)
    barge_in: bool = True
    max_session_minutes: int = Field(120, ge=1)
    stt_threads: int = Field(4, ge=1)
    unload_after_minutes: int = Field(10, ge=1)
    stage_fallback: bool = False


class DiscordVoiceMessages(_Section):
    enabled: bool = True
    reply_with_voice: Literal["mirror", "always", "never"] = "mirror"
    max_seconds: int = Field(300, ge=5, le=900)


class DiscordNotify(_Section):
    target: Literal["channel", "dm"] = "channel"
    warnings_default_level: Literal["moderate", "severe", "extreme"] = "severe"
    system_alerts: bool = True


class Discord(_Section):
    enabled: bool = False
    # leer: runtime/discord-venv (mit Zuhören im Sprachkanal, ./test-3.sh setup), sonst diese Python
    python: str = ""
    memory_minutes: int = Field(30, ge=0)  # Kurzzeitgedächtnis eines Chats; 0 = bis zum Neustart
    owner_user_ids: IdList = []
    trusted_user_ids: IdList = []
    allowed_guild_ids: IdList = []
    chat_channel_ids: IdList = []
    style: Literal["cute", "normal"] = "cute"
    startup_message: bool = True
    name_trigger: bool = True
    guest_mode: Literal["off", "skills"] = "off"
    unknown_users: Literal["ignore", "notice"] = "ignore"
    ephemeral_in_foreign_guilds: bool = True
    call_summaries: Literal["off", "topics", "transcript"] = "off"
    phone_extensions: Annotated[dict[str, str], BeforeValidator(_ids)] = {}
    quiet_hours: str = Field("22:00-07:00", pattern=_TIME_RANGE)
    max_message_chars: int = Field(4000, ge=100, le=20000)
    rate_limits: DiscordRateLimits = DiscordRateLimits()
    activities: DiscordActivities = DiscordActivities()
    voice: DiscordVoice = DiscordVoice()
    voice_messages: DiscordVoiceMessages = DiscordVoiceMessages()
    notify: DiscordNotify = DiscordNotify()


class Settings(_Section):
    general: General = General()
    server: Server = Server()
    logging: Logging = Logging()
    inference: Inference = Inference()
    search: Search = Search()
    phone: Phone = Phone()
    agent: Agent = Agent()
    storage: Storage = Storage()
    fastpaths: Fastpaths = Fastpaths()
    skills: Skills = Skills()
    sandbox: Sandbox = Sandbox()
    discord: Discord = Discord()

    def resolve(self, path: str, root: Path = REPO_ROOT) -> Path:
        """Resolve a configured path relative to the installation directory."""
        candidate = Path(path).expanduser()
        return candidate if candidate.is_absolute() else root / candidate


def _format_errors(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors():
        where = ".".join(str(part) for part in err["loc"]) or "<root>"
        lines.append(f"{where}: {err['msg']}")
    return "; ".join(lines)


def parse_settings(text: str, source: str = LOCAL_CONFIG_NAME) -> Settings:
    """Parse and validate TOML text."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SettingsError(f"{source} is not valid TOML: {exc}") from None
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        raise SettingsError(f"{source} is invalid – {_format_errors(exc)}") from None


def load_settings(path: Path | None = None, root: Path = REPO_ROOT) -> Settings:
    """Load settings from ``path``; default is config/moritz-agent.toml, else the example file.

    The test suite sets ``MORITZ_TESTS_IGNORE_LOCAL_CONFIG``: then the repository's own local file
    (written by the test scripts on a real machine) is ignored, so the tests see the defaults."""
    if path is None:
        local = root / "config" / LOCAL_CONFIG_NAME
        ignore = os.environ.get("MORITZ_TESTS_IGNORE_LOCAL_CONFIG") and root == REPO_ROOT
        path = local if local.is_file() and not ignore else root / "config" / EXAMPLE_CONFIG_NAME
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SettingsError(f"{path} does not exist") from None
    return parse_settings(text, source=str(path))
