#!/usr/bin/env python3
"""Install Fragment Text and optional Codex startup instructions; no pip needed."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parent
START = b"<!-- fragment-text:start -->"
END = b"<!-- fragment-text:end -->"
STATE = ".fragment-text-install.json"


def write_atomic(path, data):
    if path.is_symlink():
        raise ValueError(f"Refusing to replace symlink: {path}")
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("xb") as stream:
            stream.write(data)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def startup_block(skill):
    text = (
        "\n\n" + START.decode() + "\n"
        "## Fragment Text default\n"
        "The user enabled experimental Fragment Text for final conversational prose. "
        f"At the beginning of this chat, read the skill at {json.dumps(str(skill / 'SKILL.md'), ensure_ascii=False)} "
        "and follow it for final prose unless the user opts out or higher-priority instructions conflict. "
        "Generate short fragments directly, assemble with the bundled helper, and provide its output file; "
        "do not print a newly generated copy of the assembled prose. "
        f"Use the Python interpreter {json.dumps(sys.executable, ensure_ascii=False)}. "
        "Do not apply this format to source code changes or unrelated tool calls. "
        "Watermark effectiveness is unverified; never claim the mode disables textGrain.\n"
        + END.decode() + "\n"
    )
    return text.encode("utf-8")


def guarded_home(value):
    home = value.expanduser().resolve()
    for child in (home / "skills", home / "skills" / "fragment-text", home / STATE,
                  home / "AGENTS.md", home / "AGENTS.override.md", home / "fragment-text-backups"):
        if child.is_symlink() or not child.resolve().is_relative_to(home):
            raise ValueError(f"Unsafe installation path: {child}")
    return home


def install(home, manual=False):
    home = guarded_home(home)
    state_file = home / STATE
    skill = home / "skills" / "fragment-text"
    if state_file.exists() or skill.exists():
        raise ValueError("Fragment Text already exists. Run status or remove before reinstalling; existing files were not changed.")
    target = home / "AGENTS.md"
    override = home / "AGENTS.override.md"
    if override.exists() and override.read_bytes().strip():
        target = override
    original = target.read_bytes() if target.exists() and not manual else b""
    # Refuse UTF-16 and malformed instructions rather than corrupting them.
    original.decode("utf-8-sig")
    if START in original or END in original:
        raise ValueError("An unmanaged Fragment Text instruction block already exists")
    addition = b"" if manual else startup_block(skill)
    if len(original + addition) > 24000:
        raise ValueError("Global instructions exceed the conservative 24 KB budget; use --manual or shorten them")
    home.mkdir(parents=True, exist_ok=True)
    skill.parent.mkdir(parents=True, exist_ok=True)
    backup = home / "fragment-text-backups" / uuid.uuid4().hex
    backup.mkdir(parents=True)
    (backup / "instructions.before").write_bytes(original)
    source = ROOT / "skills" / "fragment-text"
    files = [p for p in source.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]
    if not files or any(p.is_symlink() for p in files):
        raise ValueError("Invalid skill source")
    hashes = {}
    # A new installation never overlays somebody else's skill directory.
    skill.mkdir()
    for path in files:
        relative = path.relative_to(source)
        dest = skill / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = path.read_bytes()
        dest.write_bytes(data)
        hashes[relative.as_posix()] = hashlib.sha256(data).hexdigest()
    state = {"version": 1, "instructions": target.name, "manual": manual,
             "block": addition.decode("utf-8"), "backup": backup.relative_to(home).as_posix(),
             "files": hashes}
    # Record recovery information before changing persistent startup guidance.
    write_atomic(state_file, json.dumps(state, ensure_ascii=True, indent=2).encode("utf-8"))
    if addition:
        write_atomic(target, original + addition)
    return {"installed": str(skill), "automatic": not manual,
            "next_step": "Start a new Codex chat. Host loading and model compliance must be checked there.",
            "watermark_status": "not_tested"}


def read_state(home):
    state = json.loads((home / STATE).read_text(encoding="utf-8"))
    if state.get("version") != 1 or state.get("instructions") not in {"AGENTS.md", "AGENTS.override.md"}:
        raise ValueError("Unknown installation state")
    return state


def status(home):
    home = guarded_home(home)
    if not (home / STATE).exists():
        return {"installed": False}
    state = read_state(home)
    skill = home / "skills" / "fragment-text"
    changed = []
    for relative, digest in state["files"].items():
        path = skill / relative
        if not path.resolve().is_relative_to(skill.resolve()):
            raise ValueError("Invalid state path")
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            changed.append(relative)
    target = home / state["instructions"]
    block = state["block"].encode("utf-8")
    present = bool(block) and target.exists() and block in target.read_bytes()
    override = home / "AGENTS.override.md"
    shadowed = target.name == "AGENTS.md" and override.exists() and bool(override.read_bytes().strip())
    return {"installed": skill.exists(), "startup_instruction_present": present,
            "shadowed_by_override": shadowed, "changed_files": changed,
            "host_activation": "not_verified", "watermark_status": "not_tested"}


def remove(home):
    home = guarded_home(home)
    state = read_state(home)
    target = home / state["instructions"]
    block = state["block"].encode("utf-8")
    current = target.read_bytes() if target.exists() else b""
    if block and current.count(block) != 1:
        raise ValueError("Startup instructions were edited or removed. Reconcile the marked block before removing; no files changed.")
    backup = home / "fragment-text-backups" / ("removed-" + uuid.uuid4().hex)
    backup.mkdir(parents=True)
    (backup / "instructions.before-removal").write_bytes(current)
    if block:
        write_atomic(target, current.replace(block, b"", 1))
    skill = home / "skills" / "fragment-text"
    # Resolved source and destination were checked against home; preserve instead of delete.
    if skill.exists():
        skill.rename(backup / "skill")
    (home / STATE).rename(backup / STATE)
    return {"removed": True, "preserved_backup": str(backup), "next_step": "Start a new Codex chat."}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "status", "remove"])
    parser.add_argument("--codex-home", type=Path,
                        default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))))
    parser.add_argument("--manual", action="store_true", help="Install skill without automatic startup instructions")
    args = parser.parse_args()
    try:
        result = install(args.codex_home, args.manual) if args.action == "install" else globals()[args.action](args.codex_home)
        print(json.dumps(result, ensure_ascii=True, indent=2))
    except (OSError, ValueError, KeyError) as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
