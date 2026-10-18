# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""install.sh / update.sh against a simulated Proxmox host (tests/moritz_agent/fake_proxmox.py)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from .test_installers import make_source, write_script

FAKE = Path(__file__).with_name("fake_proxmox.py")
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


class Pve:
    """The simulated host: fake tools on PATH, a program tree to install from."""

    def __init__(self, tmp_path: Path, version: str = "1.0") -> None:
        self.tmp = tmp_path
        self.state = tmp_path / "pve"
        self.state.mkdir()
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        for tool in (
            "pct",
            "pveam",
            "pvesm",
            "pvesh",
            "pveversion",
            "nvidia-smi",
            "ssh",
            "scp",
            "sudo",
        ):
            write_script(self.bin / tool, f'exec python3 "{FAKE}" {tool} "$@"')
        self.source = make_source(tmp_path / "src", version)
        self.devices = tmp_path / "dev"
        self.devices.mkdir()

    def env(self, **extra: str) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            PATH=f"{self.bin}:{env['PATH']}",
            FAKE_PVE=str(self.state),
            MORITZ_ALLOW_NON_ROOT="1",
            MORITZ_DEV_DIR=str(self.devices),
            MORITZ_NET_TIMEOUT="4",
        )
        env.update(extra)
        return env

    def run(self, script: str, *args: str, source: Path | None = None, **env: str):
        return subprocess.run(
            ["bash", str((source or self.source) / script), *args],
            capture_output=True,
            text=True,
            env=self.env(**env),
            timeout=120,
            stdin=subprocess.DEVNULL,
            check=False,
        )

    # -- inspection ------------------------------------------------------------------------------
    def calls(self, tool: str | None = None) -> list[list[str]]:
        path = self.state / "calls.log"
        if not path.exists():
            return []
        entries = [json.loads(line) for line in path.read_text().splitlines()]
        return [e[1:] for e in entries if tool is None or e[0] == tool]

    def pct_calls(self, command: str) -> list[list[str]]:
        return [c for c in self.calls("pct") if c and c[0] == command]

    def ct(self, ctid: str = "105") -> dict:
        return json.loads((self.state / "state.json").read_text())["ct"][ctid]

    def add_container(
        self, ctid: str = "105", installed: bool = True, ours: bool = True, status: str = "running"
    ):
        state_file = self.state / "state.json"
        state = (
            json.loads(state_file.read_text())
            if state_file.exists()
            else {"ct": {}, "templates": [], "snapshots": {}}
        )
        state["ct"][ctid] = {
            "status": status,
            "hostname": "moritz-agent",
            "config": "",
            "description": "moritz-agent Nikita - managed-by-moritz-agent-install"
            if ours
            else "mein anderer Container",
            "installed": installed,
        }
        state_file.write_text(json.dumps(state))

    def pushed_files(self, ctid: str = "105") -> list[str]:
        with tarfile.open(self.state / f"ct{ctid}" / "pushed.tgz") as archive:
            return archive.getnames()

    def exec_commands(self, ctid: str = "105") -> list[list[str]]:
        log = self.state / f"ct{ctid}" / "exec.log"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


@pytest.fixture
def pve(tmp_path) -> Pve:
    return Pve(tmp_path)


def option_value(call: list[str], name: str) -> str:
    return call[call.index(name) + 1]


# -- install.sh: new container -----------------------------------------------------------------------
def test_fresh_install_creates_the_container_and_runs_the_installer(pve):
    result = pve.run("install.sh", "--yes")
    assert result.returncode == 0, result.stdout + result.stderr
    create = pve.pct_calls("create")[0]
    assert (
        create[1] == "105"
        and create[2] == "local:vztmpl/ubuntu-26.04-standard_26.04-1_amd64.tar.zst"
    )
    assert option_value(create, "--hostname") == "moritz-agent"
    assert option_value(create, "--unprivileged") == "1"
    assert option_value(create, "--features") == "nesting=1"
    assert option_value(create, "--rootfs") == "local-lvm:80"
    assert option_value(create, "--memory") == "16384" and option_value(create, "--swap") == "2048"
    assert int(option_value(create, "--cores")) == min(18, os.cpu_count() or 4)
    assert option_value(create, "--cpuunits") == "512"
    assert option_value(create, "--onboot") == "1"
    assert option_value(create, "--net0") == "name=eth0,bridge=vmbr0,ip=dhcp,firewall=0,type=veth"
    assert option_value(create, "--tags") == "moritz-agent"
    assert "--password" not in create  # no root password anywhere on a command line
    assert "managed-by-moritz-agent-install" in option_value(create, "--description")


def test_template_is_downloaded_only_when_missing_and_newest_preferred_ubuntu_is_used(pve):
    pve.run("install.sh", "--yes")
    downloads = pve.calls("pveam")
    assert ["download", "local", "ubuntu-26.04-standard_26.04-1_amd64.tar.zst"] in downloads
    pve.add_container("105", installed=False)  # second run: template list now has it
    pve.run("install.sh", "--yes", "--ctid", "105")
    assert sum(1 for c in pve.calls("pveam") if c[0] == "download") == 1


def test_older_ubuntu_is_used_when_the_newest_is_not_offered(pve):
    result = pve.run(
        "install.sh",
        "--yes",
        FAKE_TEMPLATES="ubuntu-24.04-standard_24.04-2_amd64.tar.zst debian-12-standard_12.7-1_amd64.tar.zst",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        pve.pct_calls("create")[0][2] == "local:vztmpl/ubuntu-24.04-standard_24.04-2_amd64.tar.zst"
    )


def test_program_is_pushed_without_user_data_and_installer_started_non_interactively(pve):
    (pve.source / "passwords.txt").write_text("geheim\n")
    (pve.source / "config" / "moritz-agent.toml").write_text("lokal\n")
    result = pve.run("install.sh", "--yes", "--skip-models", "--jobs", "6")
    assert result.returncode == 0, result.stdout + result.stderr
    files = pve.pushed_files()
    assert (
        "moritz-install.sh" in files
        and "deploy/lib/host.sh" in files
        and "moritz_agent/__init__.py" in files
    )
    assert "passwords.txt" not in files and "config/moritz-agent.toml" not in files
    installer = [c for c in pve.exec_commands() if c[0].endswith("moritz-install.sh")]
    assert len(installer) == 1
    assert installer[0][0] == "/root/moritz-agent-staging/moritz-install.sh"
    assert installer[0][1:] == [
        "--non-interactive",
        "--prefix",
        "/opt/moritz-agent",
        "--skip-models",
        "--jobs",
        "6",
    ]
    assert pve.ct()["installed"] is True
    assert "192.168.1.50" in result.stdout  # the summary names the address for the Asterisk ACL


def test_container_is_started_before_the_installer_runs(pve):
    pve.run("install.sh", "--yes")
    kinds = [c[0] for c in pve.calls("pct")]
    assert kinds.index("create") < kinds.index("start") < kinds.index("push")
    assert kinds.index("push") < len(kinds) - 1 - kinds[::-1].index(
        "exec"
    )  # the installer runs after the copy


def test_network_and_resource_options_reach_pct_create(pve):
    result = pve.run(
        "install.sh", "--yes", "--ctid", "230", "--hostname", "nikita", "--storage", "local", "--disk", "100",
        "--memory", "20480", "--cores", "12", "--bridge", "vmbr1", "--vlan", "20", "--ip", "192.168.1.50/24",
        "--gateway", "192.168.1.1", "--dns", "192.168.1.1", "--timezone", "Europe/Berlin",
    )  # fmt: skip
    assert result.returncode == 0, result.stdout + result.stderr
    create = pve.pct_calls("create")[0]
    assert create[1] == "230" and option_value(create, "--hostname") == "nikita"
    assert option_value(create, "--rootfs") == "local:100"
    assert option_value(create, "--memory") == "20480" and option_value(create, "--cores") == "12"
    assert (
        option_value(create, "--net0")
        == "name=eth0,bridge=vmbr1,ip=192.168.1.50/24,firewall=0,type=veth,gw=192.168.1.1,tag=20"
    )
    assert option_value(create, "--nameserver") == "192.168.1.1"


def test_no_start_only_creates_the_container(pve):
    result = pve.run("install.sh", "--yes", "--no-start")
    assert result.returncode == 0, result.stdout + result.stderr
    assert pve.pct_calls("create") and not pve.pct_calls("start") and not pve.pct_calls("exec")


def test_installer_failure_is_reported_and_can_be_resumed(pve):
    result = pve.run("install.sh", "--yes", FAKE_INSTALL_RC="64")
    assert result.returncode == 64
    assert "setzt fort" in result.stdout + result.stderr
    assert pve.ct()["installed"] is False
    again = pve.run(
        "install.sh", "--yes"
    )  # found by hostname → resumes, does not create a second container
    assert again.returncode == 0, again.stdout + again.stderr
    assert len(pve.pct_calls("create")) == 1
    assert pve.ct()["installed"] is True


def test_dry_run_creates_nothing(pve):
    result = pve.run("install.sh", "--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[dry-run] pct create" in result.stdout
    mutating = {"create", "start", "stop", "push", "exec", "set", "snapshot", "reboot"}
    assert not [c for c in pve.calls("pct") if c[0] in mutating]
    assert not [c for c in pve.calls("pveam") if c[0] == "download"]


def test_without_confirmation_and_without_terminal_nothing_is_created(pve):
    result = pve.run("install.sh")  # no --yes, stdin is not a terminal
    assert result.returncode == 2
    assert not pve.pct_calls("create")


def test_not_on_a_proxmox_host_is_a_clear_error(pve):
    env = pve.env()
    env["PATH"] = "/usr/bin:/bin"
    result = subprocess.run(
        ["bash", str(pve.source / "install.sh"), "--yes"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 64
    assert "Proxmox" in result.stdout + result.stderr


# -- GPU ---------------------------------------------------------------------------------------------------
def test_gpu_devices_are_passed_in_when_the_host_has_them(pve):
    for node in ("nvidia0", "nvidiactl", "nvidia-uvm", "nvidia-uvm-tools"):
        (pve.devices / node).write_text("")
    result = pve.run("install.sh", "--yes")
    assert result.returncode == 0, result.stdout + result.stderr
    sets = [c for c in pve.pct_calls("set")]
    assert [c[2] for c in sets] == ["-dev0", "-dev1", "-dev2", "-dev3"]
    assert all(c[3].endswith(",gid=44") for c in sets)
    assert pve.pct_calls("reboot")


def test_gpu_auto_without_host_gpu_skips_quietly_but_yes_insists(pve):
    assert pve.run("install.sh", "--yes").returncode == 0
    assert not pve.pct_calls("set")
    (pve.tmp / "second").mkdir()
    other = Pve(pve.tmp / "second")
    result = other.run("install.sh", "--yes", "--gpu", "yes")
    assert result.returncode == 64


def test_gpu_no_never_touches_devices(pve):
    (pve.devices / "nvidia0").write_text("")
    assert pve.run("install.sh", "--yes", "--gpu", "no").returncode == 0
    assert not pve.pct_calls("set")


# -- existing container ------------------------------------------------------------------------------------
def test_install_on_an_installed_container_updates_it(pve):
    pve.add_container()
    result = pve.run("install.sh", "--yes")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not pve.pct_calls("create")
    assert pve.pct_calls("snapshot")
    updater = [c for c in pve.exec_commands() if c[0].endswith("moritz-update.sh")]
    assert updater and updater[0][1:3] == ["--non-interactive", "--prefix"]


def test_foreign_container_needs_confirmation(pve):
    pve.add_container(ours=False)
    result = pve.run("install.sh", "--ctid", "105")
    assert result.returncode == 2
    assert not pve.pct_calls("push")
    assert pve.run("install.sh", "--ctid", "105", "--yes").returncode == 0


def test_stopped_container_is_started_first(pve):
    pve.add_container(status="stopped")
    assert pve.run("update.sh", "--yes").returncode == 0
    kinds = [c[0] for c in pve.calls("pct")]
    assert kinds.index("start") < kinds.index("push")


# -- update.sh ---------------------------------------------------------------------------------------------
def test_update_takes_a_snapshot_pushes_and_runs_the_updater(pve):
    pve.add_container()
    result = pve.run(
        "update.sh", "--yes", "--drain-timeout", "30", "--keep-backups", "3", "--skip-models"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    snapshot = pve.pct_calls("snapshot")[0]
    assert snapshot[2].startswith("moritz-pre-update-")
    updater = next(c for c in pve.exec_commands() if c[0].endswith("moritz-update.sh"))
    assert updater[0] == "/root/moritz-agent-staging/moritz-update.sh"
    assert updater[1:] == [
        "--non-interactive",
        "--prefix",
        "/opt/moritz-agent",
        "--skip-models",
        "--drain-timeout",
        "30",
        "--keep-backups",
        "3",
    ]
    kinds = [c[0] for c in pve.calls("pct")]
    assert (
        kinds.index("snapshot") < kinds.index("push") < len(kinds) - 1 - kinds[::-1].index("exec")
    )
    assert not pve.pct_calls("create")


def test_update_without_container_or_installation_is_refused(pve):
    assert pve.run("update.sh", "--yes").returncode == 64
    pve.add_container(installed=False)
    result = pve.run("update.sh", "--yes")
    assert result.returncode == 64
    assert "install.sh" in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("code", "hint"), [(75, "verschoben"), (70, "wiederhergestellt"), (71, "pct rollback")]
)
def test_update_passes_the_updater_exit_codes_through(pve, code, hint):
    pve.add_container()
    result = pve.run("update.sh", "--yes", FAKE_UPDATE_RC=str(code))
    assert result.returncode == code
    assert hint in result.stdout + result.stderr


def test_old_snapshots_are_pruned(pve):
    pve.add_container()
    state_file = pve.state / "state.json"
    state = json.loads(state_file.read_text())
    state["snapshots"]["105"] = [f"moritz-pre-update-2026010{i}-000000" for i in range(1, 6)]
    state_file.write_text(json.dumps(state))
    assert pve.run("update.sh", "--yes", "--keep-snapshots", "2").returncode == 0
    remaining = json.loads(state_file.read_text())["snapshots"]["105"]
    assert len(remaining) == 2
    assert [c[2] for c in pve.pct_calls("delsnapshot")]


def test_update_continues_without_snapshot_support_unless_required(pve):
    pve.add_container()
    result = pve.run("update.sh", "--yes", FAKE_NO_SNAPSHOT="1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Snapshot nicht möglich" in result.stdout + result.stderr
    strict = pve.run("update.sh", "--yes", "--require-snapshot", FAKE_NO_SNAPSHOT="1")
    assert strict.returncode == 1
    assert (
        len([c for c in pve.exec_commands() if c[0].endswith("moritz-update.sh")]) == 1
    )  # only the first run


def test_creation_options_are_ignored_with_a_hint_on_update(pve):
    pve.add_container()
    result = pve.run("update.sh", "--yes", "--memory", "4096")
    assert result.returncode == 0
    assert "nur bei install.sh" in result.stdout + result.stderr
    assert not pve.pct_calls("set")


def test_update_dry_run_changes_nothing(pve):
    pve.add_container()
    result = pve.run("update.sh", "--dry-run")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not pve.pct_calls("snapshot") and not pve.pct_calls("push")


# -- remote mode -------------------------------------------------------------------------------------------
def test_remote_mode_copies_the_program_and_runs_the_script_on_the_host(pve):
    result = pve.run(
        "install.sh",
        "--remote",
        "admin@pve.lan",
        "--ssh-port",
        "2222",
        "--identity",
        "/k/id",
        "--yes",
        "--skip-models",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    scp = pve.calls("scp")[0]
    assert scp[:4] == ["-P", "2222", "-i", "/k/id"] and scp[-1].startswith(
        "admin@pve.lan:/tmp/moritz-agent-host-"
    )
    ssh = pve.calls("ssh")[0]
    assert ssh[0] == "-t" and "admin@pve.lan" in ssh
    remote_command = ssh[-1]
    assert (
        "install.sh" in remote_command and "--local" in remote_command and "--yes" in remote_command
    )
    assert "--remote" not in remote_command and "--identity" not in remote_command  # not forwarded
    assert pve.pct_calls("create")  # the script really ran "on the host"
    assert pve.ct()["installed"] is True


def test_remote_update_forwards_options_and_exit_code(pve):
    pve.add_container()
    result = pve.run(
        "update.sh", "--remote", "root@pve", "--yes", "--drain-timeout", "5", FAKE_UPDATE_RC="75"
    )
    assert result.returncode == 75
    assert "--drain-timeout 5" in pve.calls("ssh")[0][-1]


def test_remote_dry_run_does_not_copy_or_connect(pve):
    result = pve.run("install.sh", "--remote", "root@pve", "--dry-run")
    assert result.returncode == 0
    assert not pve.calls("scp") and not pve.calls("ssh")
    assert "[dry-run] scp" in result.stdout and "[dry-run] ssh" in result.stdout


def test_bad_options_are_usage_errors(pve):
    assert pve.run("install.sh", "--bogus").returncode == 2
    assert pve.run("install.sh", "--gpu", "vielleicht").returncode == 2
    assert pve.run("install.sh", "--ctid", "abc").returncode == 2
    assert pve.run("update.sh", "--disk").returncode == 2
