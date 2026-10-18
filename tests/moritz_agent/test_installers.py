# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""moritz-install.sh / moritz-update.sh against a small fake installation tree.

System commands that would change the machine (useradd, chown, systemctl, apt-get …) are replaced
by recording stand-ins on PATH; everything else (copying files, backups, rollback, drain handshake)
runs for real in a temporary directory.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

FAKE_COMMANDS = {
    "apt-get": 'echo "apt-get $*" >> "$FAKE_LOG"',
    "dpkg": 'echo "dpkg $*" >> "$FAKE_LOG"; exit 0',
    "useradd": 'echo "useradd $*" >> "$FAKE_LOG"; touch "$FAKE_STATE/user"',
    "usermod": 'echo "usermod $*" >> "$FAKE_LOG"',
    "chown": 'echo "chown $*" >> "$FAKE_LOG"',
    "runuser": 'echo "runuser $*" >> "$FAKE_LOG"',
    "getent": (
        'if [ "$1" = passwd ]; then [ -e "$FAKE_STATE/user" ]; exit $?; fi; '
        '[ "$2" = video ] && exit 0; exit 2'
    ),
    "systemctl": r"""
echo "systemctl $*" >> "$FAKE_LOG"
case "$1" in
  is-active) [ -e "$FAKE_STATE/active" ] ;;
  stop)
    rm -f "$FAKE_STATE/active"
    python3 - "$FAKE_PREFIX" <<'PY'
import json, sys, time
with open(sys.argv[1] + "/data/run/phone-status.json", "w") as handle:
    json.dump({"state": "stopped", "updated": time.time()}, handle)
PY
    ;;
  start|restart)
    if [ -e "$FAKE_STATE/start-fails" ] && [ ! -e "$FAKE_STATE/start-ok" ]; then exit 0; fi
    touch "$FAKE_STATE/active"
    python3 - "$FAKE_PREFIX" <<'PY'
import json, sys, time
with open(sys.argv[1] + "/data/run/phone-status.json", "w") as handle:
    json.dump({"state": "running", "updated": time.time(), "registration": "registered",
               "in_call": False, "draining": False}, handle)
PY
    ;;
esac
exit 0
""",
}


def write_script(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class Machine:
    """A fake machine: PATH with recording commands, a prefix, log and state directories."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.prefix = tmp_path / "srv" / "nikita-home"
        self.state = tmp_path / "state"
        self.bin = tmp_path / "fakebin"
        self.units = tmp_path / "units"
        self.systemd_run = tmp_path / "systemd-run"
        self.logs = tmp_path / "logs"
        self.fake_log = tmp_path / "fake.log"
        for directory in (self.state, self.bin, self.units, self.systemd_run, self.logs):
            directory.mkdir(parents=True)
        for name, body in FAKE_COMMANDS.items():
            write_script(self.bin / name, body)
        self.fake_log.write_text("")

    def env(self, **extra: str) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            PATH=f"{self.bin}:{env['PATH']}",
            FAKE_LOG=str(self.fake_log),
            FAKE_STATE=str(self.state),
            FAKE_PREFIX=str(self.prefix),
            MORITZ_ALLOW_NON_ROOT="1",
            MORITZ_SYSTEMD_DIR=str(self.systemd_run),
            MORITZ_UNIT_DIR=str(self.units),
            MORITZ_LOG_DIR=str(self.logs),
            MORITZ_VERIFY_TIMEOUT="6",
            MORITZ_START_TIMEOUT="6",
            MORITZ_MIN_DISK_GB="0",
        )
        env.update(extra)
        return env

    def commands(self) -> list[str]:
        return self.fake_log.read_text().splitlines()

    def set_service_active(self, active: bool = True) -> None:
        marker = self.state / "active"
        marker.touch() if active else marker.unlink(missing_ok=True)

    def write_status(self, *, in_call: bool, age_s: float = 0.0) -> None:
        run = self.prefix / "data" / "run"
        run.mkdir(parents=True, exist_ok=True)
        (run / "phone-status.json").write_text(
            json.dumps(
                {
                    "state": "running",
                    "updated": time.time() - age_s,
                    "registration": "registered",
                    "in_call": in_call,
                    "draining": False,
                }
            )
        )


def make_source(directory: Path, version: str, extra_files: dict[str, str] | None = None) -> Path:
    """A minimal program tree: the real scripts and unit file, a tiny payload."""
    directory.mkdir(parents=True)
    for name in ("moritz-install.sh", "moritz-update.sh", "install.sh", "update.sh"):
        shutil.copy2(REPO_ROOT / name, directory / name)
    shutil.copytree(REPO_ROOT / "deploy" / "lib", directory / "deploy" / "lib")
    (directory / "deploy" / "systemd").mkdir()
    shutil.copy2(REPO_ROOT / "deploy/systemd/moritz-agent.service", directory / "deploy/systemd/")
    (directory / "deploy" / "payload.txt").write_text(
        "moritz-install.sh\nmoritz-update.sh\ninstall.sh\nupdate.sh\ndeploy\nconfig\nmoritz_agent\nrequirements\n"
        "scripts\nthird_party/pjproject/version.mak\n"
    )
    (directory / "moritz_agent").mkdir()
    (directory / "moritz_agent" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    (directory / "config").mkdir()
    (directory / "config" / "moritz-agent.example.toml").write_text("# example\n")
    (directory / "config" / "passwords.template.txt").write_text("[sip]\npassword = agent\n")
    (directory / "requirements").mkdir()
    (directory / "requirements" / "core.lock").write_text("a==1\n")
    (directory / "requirements" / "phone.lock").write_text("b==1\n")
    (directory / "scripts").mkdir()
    write_script(directory / "scripts" / "build-pjsip.sh", "exit 0")
    write_script(directory / "scripts" / "setup-env.sh", "exit 0")
    (directory / "third_party" / "pjproject").mkdir(parents=True)
    (directory / "third_party" / "pjproject" / "version.mak").write_text(
        "export PJ_VERSION_MAJOR := 2\n"
    )
    for relative, content in (extra_files or {}).items():
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return directory


def run_script(machine: Machine, source: Path, script: str, *args: str, **env: str):
    return subprocess.run(
        ["bash", str(source / script), "--prefix", str(machine.prefix), *args],
        capture_output=True,
        text=True,
        env=machine.env(**env),
        timeout=120,
        check=False,
    )


INSTALL_ARGS = ("--skip-packages", "--skip-env", "--skip-models", "--non-interactive")


@pytest.fixture
def machine(tmp_path) -> Machine:
    return Machine(tmp_path)


def install(machine: Machine, source: Path, *extra: str):
    return run_script(machine, source, "moritz-install.sh", *INSTALL_ARGS, *extra)


# -- payload ---------------------------------------------------------------------------------------
def shell(command: str, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", f'source "{REPO_ROOT}/deploy/lib/common.sh"; {command}'],
        capture_output=True,
        text=True,
        cwd=cwd,
        check=False,
    )


def test_every_path_in_payload_list_exists_in_the_repository():
    result = shell('payload_paths "$PWD"')
    assert result.returncode == 0, result.stderr
    paths = result.stdout.split()
    assert "moritz_agent" in paths and "install.sh" in paths and "third_party/pjproject" in paths
    missing = [p for p in paths if not (REPO_ROOT / p).exists()]
    assert not missing, missing


def test_payload_never_contains_user_data(tmp_path):
    tree = make_source(tmp_path / "src", "1")
    (tree / "config" / "moritz-agent.toml").write_text("local = true\n")
    (tree / "config" / "site.local.toml").write_text("local = true\n")
    (tree / "moritz_agent" / "__pycache__").mkdir()
    (tree / "moritz_agent" / "__pycache__" / "x.pyc").write_bytes(b"\0")
    (tree / "passwords.txt").write_text("secret\n")
    (tree / "models").mkdir()
    (tree / "models" / "big.bin").write_bytes(b"\0")
    result = shell("payload_files .", cwd=tree)
    files = result.stdout.split()
    assert "config/moritz-agent.example.toml" in files and "moritz_agent/__init__.py" in files
    for forbidden in ("config/moritz-agent.toml", "config/site.local.toml", "passwords.txt"):
        assert forbidden not in files
    assert not [f for f in files if "__pycache__" in f or f.startswith("models/")]


def test_payload_list_rejects_absolute_and_parent_paths(tmp_path):
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / "payload.txt").write_text("../etc\n")
    assert shell("payload_paths .", cwd=tmp_path).returncode != 0
    (tmp_path / "deploy" / "payload.txt").write_text("/etc\n")
    assert shell("payload_paths .", cwd=tmp_path).returncode != 0


def test_sync_code_replaces_files_and_removes_only_stale_payload_files(tmp_path):
    first = make_source(tmp_path / "v1", "1", {"scripts/old-tool.sh": "old\n"})
    second = make_source(tmp_path / "v2", "2")
    target = tmp_path / "target"
    for kept in ("passwords.txt", "config/moritz-agent.toml", "models/m.bin", "data/x"):
        (target / kept).parent.mkdir(parents=True, exist_ok=True)
        (target / kept).write_text("mine\n")
    assert shell(f'sync_code "{first}" "{target}"').returncode == 0
    assert (target / "scripts" / "old-tool.sh").exists()
    assert "1" in (target / "moritz_agent" / "__init__.py").read_text()
    assert shell(f'sync_code "{second}" "{target}"').returncode == 0
    assert not (
        target / "scripts" / "old-tool.sh"
    ).exists()  # was in the old payload, not in the new
    assert '"2"' in (target / "moritz_agent" / "__init__.py").read_text()
    for kept in ("passwords.txt", "config/moritz-agent.toml", "models/m.bin", "data/x"):
        assert (target / kept).read_text() == "mine\n", kept


# -- installer -------------------------------------------------------------------------------------
def test_fresh_install_creates_user_files_and_keeps_secrets_private(machine, tmp_path):
    source = make_source(tmp_path / "src", "1.0")
    result = install(machine, source, "--no-service")
    assert result.returncode == 0, result.stdout + result.stderr
    prefix = machine.prefix
    assert (prefix / "moritz_agent" / "__init__.py").exists()
    passwords = prefix / "passwords.txt"
    assert stat.S_IMODE(passwords.stat().st_mode) == 0o600
    assert "password = agent" in passwords.read_text()
    assert "Startwert" in result.stdout + result.stderr  # the weak default password is flagged
    assert (prefix / "config" / "moritz-agent.toml").read_text() == "# example\n"
    for directory in (
        "data/logs",
        "data/run",
        "data/state",
        "models",
        "runtime",
        "assets/audio/cache",
    ):
        assert (prefix / directory).is_dir(), directory
    assert stat.S_IMODE((prefix / "backups").stat().st_mode) == 0o700
    commands = machine.commands()
    assert any(c.startswith("useradd --system") and "moritz-agent" in c for c in commands)
    assert any(c.startswith("chown -R moritz-agent:moritz-agent") for c in commands)
    assert (prefix / "data" / "state" / "payload-manifest.txt").is_file()


def test_reinstall_keeps_passwords_and_configuration(machine, tmp_path):
    source = make_source(tmp_path / "src", "1.0")
    assert install(machine, source, "--no-service").returncode == 0
    (machine.prefix / "passwords.txt").write_text("[sip]\npassword = mein-geheimes-passwort\n")
    (machine.prefix / "config" / "moritz-agent.toml").write_text("# angepasst\n")
    assert install(machine, source, "--no-service").returncode == 0
    assert "mein-geheimes-passwort" in (machine.prefix / "passwords.txt").read_text()
    assert (machine.prefix / "config" / "moritz-agent.toml").read_text() == "# angepasst\n"


def test_install_never_prints_secrets(machine, tmp_path):
    source = make_source(tmp_path / "src", "1.0")
    assert install(machine, source, "--no-service").returncode == 0
    (machine.prefix / "passwords.txt").write_text("[sip]\npassword = streng-geheim-12345\n")
    result = install(machine, source, "--no-service")
    assert "streng-geheim-12345" not in result.stdout + result.stderr
    logs = "".join(p.read_text() for p in machine.logs.glob("*"))
    assert "streng-geheim-12345" not in logs


def test_dry_run_changes_nothing(machine, tmp_path):
    source = make_source(tmp_path / "src", "1.0")
    result = run_script(machine, source, "moritz-install.sh", "--dry-run", *INSTALL_ARGS)
    assert result.returncode == 0, result.stderr
    assert "[dry-run]" in result.stdout
    assert not machine.prefix.exists()
    assert [c for c in machine.commands() if not c.startswith(("dpkg",))] == []


def test_install_registers_a_systemd_unit_for_the_prefix(machine, tmp_path):
    source = make_source(tmp_path / "src", "1.0")
    machine.systemd_run.mkdir(exist_ok=True)
    result = install(machine, source)
    assert result.returncode == 0, result.stdout + result.stderr
    unit = (machine.units / "moritz-agent.service").read_text()
    assert f"WorkingDirectory={machine.prefix}" in unit
    assert f"ExecStart={machine.prefix}/moritz-agent run" in unit
    assert "/opt/moritz-agent" not in unit
    assert "User=moritz-agent" in unit
    commands = machine.commands()
    assert "systemctl daemon-reload" in commands
    assert "systemctl enable moritz-agent.service" in commands
    assert "systemctl restart moritz-agent.service" in commands
    assert "Dienst läuft" in result.stdout and "SIP-Registrierung: ok" in result.stdout


def test_installer_rejects_bad_usage(machine, tmp_path):
    source = make_source(tmp_path / "src", "1.0")
    assert run_script(machine, source, "moritz-install.sh", "--bogus").returncode == 2
    assert (
        subprocess.run(
            ["bash", str(source / "moritz-install.sh"), "--prefix", "relativ"],
            capture_output=True,
            env=machine.env(),
            check=False,
        ).returncode
        == 2
    )


# -- updater ---------------------------------------------------------------------------------------
UPDATE_ARGS = ("--skip-models", "--skip-env", "--no-service")


def installed(
    machine: Machine, tmp_path: Path, version: str = "1.0", service: bool = False
) -> None:
    old = make_source(tmp_path / "old", version, {"scripts/old-tool.sh": "old\n"})
    assert install(machine, old, *([] if service else ["--no-service"])).returncode == 0
    (machine.prefix / "passwords.txt").write_text("[sip]\npassword = mein-passwort\n")
    (machine.prefix / "config" / "moritz-agent.toml").write_text("# meine Konfiguration\n")


def update(machine: Machine, source: Path, *extra: str, **env: str):
    return run_script(machine, source, "moritz-update.sh", *extra, **env)


def test_update_replaces_the_program_and_keeps_user_data(machine, tmp_path):
    installed(machine, tmp_path)
    new = make_source(tmp_path / "new", "2.0", {"scripts/new-tool.sh": "new\n"})
    (machine.prefix / "models").mkdir(exist_ok=True)
    (machine.prefix / "models" / "voice.onnx").write_text("modell\n")
    result = update(machine, new, *UPDATE_ARGS)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1.0 → 2.0" in result.stdout
    assert '"2.0"' in (machine.prefix / "moritz_agent" / "__init__.py").read_text()
    assert (machine.prefix / "scripts" / "new-tool.sh").exists()
    assert not (machine.prefix / "scripts" / "old-tool.sh").exists()
    assert "mein-passwort" in (machine.prefix / "passwords.txt").read_text()
    assert (
        machine.prefix / "config" / "moritz-agent.toml"
    ).read_text() == "# meine Konfiguration\n"
    assert (machine.prefix / "models" / "voice.onnx").read_text() == "modell\n"
    backups = list((machine.prefix / "backups").iterdir())
    assert len(backups) == 1
    backup = backups[0]
    assert stat.S_IMODE(backup.stat().st_mode) == 0o700
    assert (backup / "code.tgz").is_file()
    assert "mein-passwort" in (backup / "passwords.txt").read_text()


def test_update_keeps_only_the_newest_backups(machine, tmp_path):
    installed(machine, tmp_path)
    (machine.prefix / "backups" / "20200101-000000").mkdir()
    (machine.prefix / "backups" / "20200102-000000").mkdir()
    new = make_source(tmp_path / "new", "2.0")
    assert update(machine, new, *UPDATE_ARGS, "--keep-backups", "2").returncode == 0
    names = sorted(p.name for p in (machine.prefix / "backups").iterdir())
    assert len(names) == 2 and "20200101-000000" not in names


def test_update_without_installation_is_refused(machine, tmp_path):
    new = make_source(tmp_path / "new", "2.0")
    result = update(machine, new, *UPDATE_ARGS)
    assert result.returncode == 64
    assert "install.sh" in result.stdout + result.stderr


def test_update_refuses_to_run_from_the_installation_itself(machine, tmp_path):
    installed(machine, tmp_path)
    result = run_script(machine, machine.prefix, "moritz-update.sh", *UPDATE_ARGS)
    assert result.returncode == 64


def test_update_is_postponed_while_a_call_is_active(machine, tmp_path):
    installed(machine, tmp_path, service=True)
    machine.set_service_active()
    machine.write_status(in_call=True)
    new = make_source(tmp_path / "new", "2.0")
    result = update(machine, new, "--skip-models", "--skip-env", "--drain-timeout", "2")
    assert result.returncode == 75, result.stdout + result.stderr
    assert '"1.0"' in (machine.prefix / "moritz_agent" / "__init__.py").read_text()  # untouched
    assert not (machine.prefix / "data" / "run" / "drain").exists()  # calls are accepted again
    assert not list((machine.prefix / "backups").iterdir())
    assert "systemctl stop moritz-agent.service" not in machine.commands()


def test_update_drains_stops_and_restarts_the_service(machine, tmp_path):
    installed(machine, tmp_path, service=True)
    machine.set_service_active()
    machine.write_status(in_call=False)
    new = make_source(tmp_path / "new", "2.0")
    seen_before = len(machine.commands())
    result = update(machine, new, "--skip-models", "--skip-env")
    assert result.returncode == 0, result.stdout + result.stderr
    commands = machine.commands()[seen_before:]  # only what the update did
    assert commands.index("systemctl stop moritz-agent.service") < commands.index(
        "systemctl restart moritz-agent.service"
    )
    assert not (machine.prefix / "data" / "run" / "drain").exists()
    assert '"2.0"' in (machine.prefix / "moritz_agent" / "__init__.py").read_text()


def test_failed_start_rolls_back_to_the_old_version(machine, tmp_path):
    installed(machine, tmp_path, service=True)
    machine.set_service_active()
    machine.write_status(in_call=False)
    (machine.state / "start-fails").touch()  # the new version never reports "running"
    new = make_source(tmp_path / "new", "2.0", {"scripts/new-tool.sh": "new\n"})
    original = (machine.prefix / "moritz_agent" / "__init__.py").read_text()

    # the rollback restarts the service, which must work again
    def allow_start_after_rollback() -> None:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if "systemctl start moritz-agent.service" in machine.commands():
                (machine.state / "start-ok").touch()
                return
            time.sleep(0.05)

    import threading

    watcher = threading.Thread(target=allow_start_after_rollback, daemon=True)
    watcher.start()
    result = update(machine, new, "--skip-models", "--skip-env", MORITZ_START_TIMEOUT="3")
    assert result.returncode == 70, result.stdout + result.stderr
    assert (machine.prefix / "moritz_agent" / "__init__.py").read_text() == original
    assert not (machine.prefix / "scripts" / "new-tool.sh").exists()
    assert (machine.prefix / "scripts" / "old-tool.sh").exists()
    assert "mein-passwort" in (machine.prefix / "passwords.txt").read_text()
    assert not (machine.prefix / "data" / "run" / "drain").exists()
    assert "wiederhergestellt" in result.stdout + result.stderr


def test_update_dry_run_changes_nothing(machine, tmp_path):
    installed(machine, tmp_path)
    new = make_source(tmp_path / "new", "2.0")
    result = update(machine, new, *UPDATE_ARGS, "--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"1.0"' in (machine.prefix / "moritz_agent" / "__init__.py").read_text()
    assert not list((machine.prefix / "backups").iterdir())


def test_update_rebuilds_the_environment_only_when_packages_changed(machine, tmp_path):
    installed(machine, tmp_path)
    runtime = machine.prefix / "runtime"
    (runtime / "venv" / "bin").mkdir(parents=True)
    (runtime / "venv" / "bin" / "python").symlink_to(sys.executable)
    recorder = machine.root / "env-builds.log"
    new = make_source(tmp_path / "new", "2.0")
    write_script(
        new / "scripts" / "setup-env.sh",
        f'echo "setup $*" >> "{recorder}"; mkdir -p "$2/bin"; ln -sf {sys.executable} "$2/bin/python"',
    )
    write_script(new / "scripts" / "build-pjsip.sh", f'echo "pjsip $*" >> "{recorder}"')
    args = ("--skip-models", "--no-service")
    first = update(machine, new, *args)
    assert first.returncode == 0, first.stdout + first.stderr
    assert "setup --venv" in recorder.read_text()  # no hash recorded yet → built
    assert (runtime / ".env-hash").is_file()
    assert (runtime / "venv.prev").is_dir()
    recorder.write_text("")
    newer = make_source(tmp_path / "newer", "2.1")
    write_script(newer / "scripts" / "setup-env.sh", f'echo "setup $*" >> "{recorder}"')
    write_script(newer / "scripts" / "build-pjsip.sh", f'echo "pjsip $*" >> "{recorder}"')
    # same lock files and PJSIP version as before → no rebuild; build-pjsip.sh is part of the hash,
    # so give the new tree the identical script
    shutil.copy2(new / "scripts" / "build-pjsip.sh", newer / "scripts" / "build-pjsip.sh")
    second = update(machine, newer, *args)
    assert second.returncode == 0, second.stdout + second.stderr
    assert recorder.read_text() == ""
    assert "unverändert" in second.stdout
