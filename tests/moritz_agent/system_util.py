# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""A complete main process without child processes: runtime, both APIs, fake model, fixtures."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx

from moritz_agent.api.app import create_app, create_internal_app
from moritz_agent.api.auth import Authenticator
from moritz_agent.api.context import AppContext
from moritz_agent.config.reload import ConfigManager
from moritz_agent.inference import InferenceClient
from moritz_agent.runtime import Runtime
from moritz_agent.setup import files
from moritz_agent.skills.clock import FixedClock

from . import weather_fixtures as wf
from .fake_model import FakeModel
from .skills_util import SUNDAY_EVENING, default_routes

ROOT = Path(__file__).resolve().parents[2]
WEB_USER = "moritz"
WEB_PASSWORD = "Web-Pw#42%ü"
SIP_PASSWORD = "SipPw-9;x!Q"
TANKE_KEY = "tk-1234567890abcdef"

PASSWORDS = f"""[sip]
username = agent
auth_username = agent
password = {SIP_PASSWORD}
display_name = Anton
registrar = 192.168.1.176
port = 5060
transport = udp
extension = 999

[web_login]
username = {WEB_USER if True else ""}
password = {WEB_PASSWORD}

[sandbox_ssh]
enabled = false

[optional_services]
tankerkoenig_api_key = {TANKE_KEY}
"""


OWNER_ID = "1001"
TRUSTED_ID = "1002"
STRANGER_ID = "1999"
BOT_TOKEN = "test-only-bot-token-" + "0123456789abcdef" * 3
CHANNEL_ID = "5550001"
ADMIN_PIN = "47110815"
CREDENTIALS = [WEB_PASSWORD, SIP_PASSWORD, TANKE_KEY, BOT_TOKEN, ADMIN_PIN]


def make_tree(
    tmp_path: Path, *, web_login: bool = True, discord: bool = False, notes: bool = False
) -> Path:
    """Config and passwords of a test installation (the program files stay in the repository)."""
    (tmp_path / "config").mkdir(exist_ok=True)
    toml = (ROOT / "config/moritz-agent.example.toml").read_text(encoding="utf-8")
    toml = toml.replace('host = "0.0.0.0"', 'host = "127.0.0.1"')
    toml = toml.replace(
        'database = "data/moritz-agent.sqlite3"', f'database = "{tmp_path}/db.sqlite3"'
    )
    toml = toml.replace(
        'passwords_file = "passwords.txt"', f'passwords_file = "{tmp_path}/passwords.txt"'
    )
    # never the real model of the machine (/home/models on Sophie-1): no KoboldCpp in tests
    toml = files.set_value(toml, "inference", "model", f'"{tmp_path}/no-model.gguf"')
    if notes:
        toml = toml.replace("[skills.notes]\nenabled = false", "[skills.notes]\nenabled = true", 1)
    if discord:
        head, _, rest = toml.partition("[discord]")
        rest = rest.replace("enabled = false", "enabled = true", 1)
        rest = rest.replace("owner_user_ids = []", f'owner_user_ids = ["{OWNER_ID}"]', 1)
        rest = rest.replace("trusted_user_ids = []", f'trusted_user_ids = ["{TRUSTED_ID}"]', 1)
        toml = head + "[discord]" + rest
    (tmp_path / "config" / "moritz-agent.toml").write_text(toml, encoding="utf-8")
    prompt = tmp_path / "moritz_agent" / "agent" / "prompts"
    prompt.mkdir(parents=True, exist_ok=True)
    (prompt / "phone.de.md").write_text(
        (ROOT / "moritz_agent/agent/prompts/phone.de.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    text = (
        PASSWORDS
        if web_login
        else PASSWORDS.replace(f"username = {WEB_USER}", "username =").replace(
            f"password = {WEB_PASSWORD}", "password ="
        )
    )
    if discord:
        text += f"\n[discord]\nbot_token = {BOT_TOKEN}\nchannel_id = {CHANNEL_ID}\nadmin_pin = {ADMIN_PIN}\n"
    path = tmp_path / "passwords.txt"
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return tmp_path


@dataclass
class System:
    runtime: Runtime
    ctx: AppContext
    config: ConfigManager
    model: FakeModel | None
    tree: Path
    app: object
    internal_app: object

    def client(
        self, *, ip: str = "127.0.0.1", internal: bool = False, **kwargs
    ) -> httpx.AsyncClient:
        app = self.internal_app if internal else self.app
        transport = httpx.ASGITransport(app=app, client=(ip, 5000))
        return httpx.AsyncClient(transport=transport, base_url="http://testserver", **kwargs)

    async def login(self, client: httpx.AsyncClient) -> httpx.Response:
        return await client.post(
            "/api/login", json={"username": WEB_USER, "password": WEB_PASSWORD}
        )

    def internal_headers(self) -> dict[str, str]:
        return {"X-Internal-Token": self.ctx.internal_token}

    def admin_headers(self) -> dict[str, str]:
        return {"X-Admin-Token": self.ctx.admin_token}


@contextlib.asynccontextmanager
async def running_system(
    tmp_path: Path,
    *,
    model: bool = False,
    web_login: bool = True,
    discord: bool = False,
    notes: bool = False,
    routes: dict | None = None,
    delay_s: float = 0.0,
    auth_clock=None,
) -> AsyncIterator[System]:
    tree = make_tree(tmp_path, web_login=web_login, discord=discord, notes=notes)
    config = ConfigManager(root=tree)
    config.load()
    fake = FakeModel() if model else None
    client = InferenceClient("http://127.0.0.1:1", transport=fake.transport()) if fake else None
    table = default_routes()
    table.update(routes or {})
    inner = wf.mock_transport(table)

    async def answer(request: httpx.Request) -> httpx.Response:
        if delay_s:
            import asyncio

            await asyncio.sleep(delay_s)
        return await inner.handle_async_request(request)

    runtime = Runtime(
        config,
        ROOT,
        clock=FixedClock(SUNDAY_EVENING),
        manage_processes=False,
        inference_client=client,
        providers_transport=httpx.MockTransport(answer),
        providers_cache_dir=tmp_path / "cache",
    )
    await runtime.start()
    kwargs = {"clock": auth_clock} if auth_clock else {}
    ctx = AppContext(
        runtime=runtime,
        config=config,
        auth=Authenticator(lambda: config.current, **kwargs),
        root=ROOT,
        data_root=tmp_path,
        secure_cookie=False,
    )
    system = System(runtime, ctx, config, fake, tree, create_app(ctx), create_internal_app(ctx))
    try:
        yield system
    finally:
        await runtime.stop()
