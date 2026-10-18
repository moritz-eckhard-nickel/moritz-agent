# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""A tiny stand-in for the Proxmox command line tools (pct, pveam, pvesm, pvesh, pveversion, ssh, scp).

Used by test_host_scripts.py through launcher scripts on PATH: ``fake_proxmox.py <tool> <args…>``.
State lives in the directory $FAKE_PVE (JSON + files), every call is appended to calls.log.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

STATE = Path(os.environ["FAKE_PVE"])
TEMPLATES = os.environ.get(
    "FAKE_TEMPLATES",
    "ubuntu-24.04-standard_24.04-2_amd64.tar.zst ubuntu-25.10-standard_25.10-1_amd64.tar.zst "
    "ubuntu-26.04-standard_26.04-1_amd64.tar.zst debian-12-standard_12.7-1_amd64.tar.zst",
).split()


def log_call(tool: str, args: list[str]) -> None:
    with (STATE / "calls.log").open("a") as handle:
        handle.write(json.dumps([tool, *args]) + "\n")


def load() -> dict:
    path = STATE / "state.json"
    return (
        json.loads(path.read_text())
        if path.exists()
        else {"ct": {}, "templates": [], "snapshots": {}}
    )


def save(state: dict) -> None:
    (STATE / "state.json").write_text(json.dumps(state))


def option(args: list[str], name: str) -> str | None:
    return args[args.index(name) + 1] if name in args else None


def pct(args: list[str]) -> int:
    state = load()
    cmd = args[0]
    if cmd == "list":
        print("VMID       Status     Lock         Name")
        for ctid, ct in sorted(state["ct"].items()):
            print(f"{ctid:<10} {ct['status']:<10} {'':<12} {ct['hostname']}")
        return 0
    ctid = args[1] if len(args) > 1 else ""
    if cmd == "create":
        if ctid in state["ct"]:
            print("CT already exists", file=sys.stderr)
            return 1
        state["ct"][ctid] = {
            "status": "stopped",
            "hostname": option(args, "--hostname") or "CT" + ctid,
            "config": " ".join(args[2:]),
            "description": option(args, "--description") or "",
            "installed": False,
            "running_calls": False,
        }
        save(state)
        return 0
    if ctid not in state["ct"]:
        print(f"Configuration file 'nodes/pve/lxc/{ctid}.conf' does not exist", file=sys.stderr)
        return 2
    ct = state["ct"][ctid]
    if cmd == "status":
        print(f"status: {ct['status']}")
        return 0
    if cmd == "config":
        print(f"description: {ct['description']}")
        print(f"hostname: {ct['hostname']}")
        return 0
    if cmd in ("start", "reboot"):
        ct["status"] = "running"
    elif cmd == "stop":
        ct["status"] = "stopped"
    elif cmd == "set":
        ct.setdefault("set", []).append(args[2:])
    elif cmd == "push":
        target = STATE / f"ct{ctid}"
        target.mkdir(exist_ok=True)
        shutil.copy(args[2], target / "pushed.tgz")
    elif cmd == "snapshot":
        if os.environ.get("FAKE_NO_SNAPSHOT"):
            print("snapshot feature is not available", file=sys.stderr)
            return 255
        state["snapshots"].setdefault(ctid, []).append(args[2])
    elif cmd == "listsnapshot":
        for name in state["snapshots"].get(ctid, []):
            print(f"`-> {name}      2026-10-18 19:00:00     vor moritz-agent Update")
        print("`-> current                                     You are here!")
    elif cmd == "delsnapshot":
        state["snapshots"][ctid].remove(args[2])
    elif cmd == "exec":
        save(state)
        return pct_exec(ctid, ct, args[args.index("--") + 1 :])
    save(state)
    return 0


def pct_exec(ctid: str, ct: dict, command: list[str]) -> int:
    base = STATE / f"ct{ctid}"
    base.mkdir(exist_ok=True)
    with (base / "exec.log").open("a") as handle:
        handle.write(json.dumps(command) + "\n")
    head = command[0]
    if head == "getent":
        if command[1] == "hosts":
            return 0
        if command[1:] == ["group", "video"]:
            print("video:x:44:")
            return 0
        return 2
    if command[:2] == ["hostname", "-I"]:
        print("192.168.1.50 ")
        return 0
    if head == "test":
        return 0 if ct["installed"] else 1
    if head == "bash" and command[1] == "-c":
        staging = base / "staging"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir()
        with tarfile.open(base / "pushed.tgz") as archive:
            archive.extractall(staging, filter="data")
        return 0
    if head.endswith("moritz-install.sh") or head.endswith("moritz-update.sh"):
        rc = int(
            os.environ.get(
                "FAKE_UPDATE_RC" if head.endswith("update.sh") else "FAKE_INSTALL_RC", "0"
            )
        )
        state = load()
        if rc == 0 and head.endswith("install.sh"):
            state["ct"][ctid]["installed"] = True
        save(state)
        return rc
    return 0


def pveam(args: list[str]) -> int:
    state = load()
    if args[0] == "update":
        return 0
    if args[0] == "available":
        for name in TEMPLATES:
            print(f"system          {name}")
        return 0
    if args[0] == "list":
        for name in state["templates"]:
            print(f"{args[1]}:vztmpl/{name}   120MB")
        return 0
    if args[0] == "download":
        state["templates"].append(args[2])
        save(state)
        return 0
    return 1


def pvesm(args: list[str]) -> int:
    content = option(args, "--content")
    print(
        "Name             Type     Status           Total            Used       Available        %"
    )
    if content == "rootdir":
        print(
            "local-lvm     lvmthin     active       100000000        1000000        99000000    1.00%"
        )
        print(
            "local             dir     active       100000000        1000000        99000000    1.00%"
        )
    else:
        print(
            "local             dir     active       100000000        1000000        99000000    1.00%"
        )
    return 0


def main() -> int:
    tool, args = sys.argv[1], sys.argv[2:]
    log_call(tool, args)
    if tool == "pct":
        return pct(args)
    if tool == "pveam":
        return pveam(args)
    if tool == "pvesm":
        return pvesm(args)
    if tool == "pvesh":
        print("105")
        return 0
    if tool == "pveversion":
        print("pve-manager/8.2.4/faa83925c9641325 (running kernel: 6.8.4-2-pve)")
        return 0
    if tool == "nvidia-smi":
        print("550.90.07")
        return 0
    if tool == "scp":  # scp [-P port] [-i key] LOCAL HOST:REMOTE → plain copy
        paths = [a for a in args if not a.startswith("-")]
        local, remote = paths[-2], paths[-1].split(":", 1)[1]
        shutil.copy(local, remote)
        return 0
    if tool == "ssh":  # ssh [-t] [-p port] [-i key] HOST COMMAND → run the command here
        command = args[-1]
        return subprocess.run(["bash", "-c", command], check=False).returncode
    if tool == "sudo":
        return subprocess.run(args, check=False).returncode
    print("unknown tool", shlex.quote(tool), file=sys.stderr)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
