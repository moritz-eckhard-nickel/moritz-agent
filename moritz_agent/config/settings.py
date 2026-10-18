# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Typed settings for config/moritz-agent.toml (CFG-08, ADR-012).

Every key of ``config/moritz-agent.example.toml`` has a field with the same default. Unknown
keys are rejected, so typos surface at startup instead of being silently ignored.
Credentials never live here – they are in passwords.txt (see ``secrets.py``).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

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
    koboldcpp_script: str = "koboldcpp.py"
    model: str = "models/llm/Qwen3-30B-A3B-Instruct-2507-UD-Q3_K_XL.gguf"
    context_size: int = Field(4096, ge=512)
    gpu_layers: int = 999
    moe_cpu_layers: int = Field(24, ge=0)
    use_cuda: bool = True
    jinja: bool = True
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
    initial_prompt: str = "Nikita, Moritz, Hessen, Frankfurt."


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


class Phone(_Section):
    enabled: bool = True
    assistant_name: str = "Nikita"
    greeting_text: str = "Hallo Moritz, hier ist Nikita. Was kann ich für dich tun?"
    local_sip_port: int = Field(5060, ge=1, le=65535)
    rtp_port_start: int = Field(40000, ge=1024, le=65000)
    rtp_port_count: int = Field(200, ge=4, le=10000)
    codecs: list[str] = ["G722/16000", "PCMA/8000", "PCMU/8000"]
    allowed_source_ips: list[str] = ["192.168.1.176"]
    max_concurrent_calls: Literal[1] = 1
    ring_seconds: float = Field(3.0, ge=0, le=30)
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
    tools: list[str] = ["get_current_time", "web_search"]
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


class Sandbox(_Section):
    connect_timeout_s: int = Field(10, ge=1)


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
    sandbox: Sandbox = Sandbox()

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
    """Load settings from ``path``; default is config/moritz-agent.toml, else the example file."""
    if path is None:
        local = root / "config" / LOCAL_CONFIG_NAME
        path = local if local.is_file() else root / "config" / EXAMPLE_CONFIG_NAME
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SettingsError(f"{path} does not exist") from None
    return parse_settings(text, source=str(path))
