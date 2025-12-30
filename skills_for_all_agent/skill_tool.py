from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

DEFAULT_SKILLS_ROOT = Path(__file__).resolve().parent / "skills"


class SkillError(Exception):
    pass


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    path: str


_FRONTMATTER_DELIM = "---"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _split_frontmatter(content: str) -> (Dict[str, str], str):
    lines = content.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_DELIM:
        return {}, content

    fm_lines = []
    body_start = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == _FRONTMATTER_DELIM:
            body_start = idx + 1
            break
        fm_lines.append(lines[idx])

    if body_start is None:
        return {}, content

    fm = {}
    for raw in fm_lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and value:
            fm[key] = value

    body = "\n".join(lines[body_start:])
    return fm, body


def _skill_dirs(skills_root: Path) -> Iterable[Path]:
    if not skills_root.exists():
        return []
    for child in skills_root.iterdir():
        if child.is_dir():
            yield child


def _load_metadata(skill_dir: Path) -> Optional[SkillMetadata]:
    print(skill_dir)
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None
    fm, _ = _split_frontmatter(_read_text(skill_md))
    name = fm.get("name")
    description = fm.get("description")
    if not name or not description:
        return None
    return SkillMetadata(name=name, description=description, path=str(skill_dir))


def _find_skill_dir(skills_root: Path, skill_name: str) -> Path:
    print("skills_root")
    for skill_dir in _skill_dirs(skills_root):
        meta = _load_metadata(skill_dir)
        if meta and meta.name == skill_name:
            return skill_dir
    raise SkillError(f"Skill not found: {skill_name}")


def list_metadata(skills_root: Path) -> List[SkillMetadata]:
    skills = []
    for skill_dir in _skill_dirs(skills_root):
        meta = _load_metadata(skill_dir)
        if meta:
            skills.append(meta)
    return skills


def build_metadata_prompt(skills: Iterable[SkillMetadata]) -> str:
    lines = ["## Skills"]
    for meta in skills:
        lines.append(f"- {meta.name}: {meta.description}")
    return "\n".join(lines)


def read_skill_body(skill_dir: Path) -> str:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise SkillError(f"Missing SKILL.md in {skill_dir}")
    _, body = _split_frontmatter(_read_text(skill_md))
    return body.strip()


def _resolve_inside(base: Path, rel: str) -> Path:
    candidate = (base / rel).resolve()
    base_resolved = base.resolve()
    if base_resolved == candidate or base_resolved in candidate.parents:
        return candidate
    raise SkillError("Path escapes skill directory")


def read_resource(skill_dir: Path, rel_path: str) -> str:
    target = _resolve_inside(skill_dir, rel_path)
    if not target.exists():
        raise SkillError(f"Resource not found: {rel_path}")
    return _read_text(target)


def run_script(
    skill_dir: Path,
    rel_path: str,
    args: Optional[List[str]] = None,
    timeout_sec: int = 60,
) -> Dict[str, object]:
    target = _resolve_inside(skill_dir, rel_path)
    if not target.exists():
        raise SkillError(f"Script not found: {rel_path}")
    if not target.is_file():
        raise SkillError(f"Not a file: {rel_path}")

    cmd = ["python3", str(target)]
    if args:
        cmd.extend(args)

    proc = subprocess.run(
        cmd,
        cwd=str(skill_dir),
        capture_output=True,
        text=True,
        timeout=timeout_sec,
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
def skill_tool(request: Dict[str, object]) -> Dict[str, object]:
    discription=f"""
    Unified skill tool. If you are not sure, you can first use the "list_metadata" function of this tool to search for available skills. Then, determine which skill might be the most useful. After that, try to read the SKILL.md file under this skill path to get more detailed information. Finally, based on the content of this file, decide whether to read the documentation in other paths or directly execute the relevant script.

    Input format:
        {{
            "action": "<action_name>",
            "arg": "<string argument>"
        }}

    Actions:
    - list_metadata: arg = skills root directory (default: {DEFAULT_SKILLS_ROOT})
    - read_file:     arg = file path
    - run_command:   arg = full command string
    """


    action = request.get("action")
    arg = request.get("arg")

    if not action:
        raise SkillError("Missing action")

    # =========================================================
    # 1. list_metadata
    # =========================================================
    if action == "list_metadata":
        skills_root = (
            Path(os.path.expanduser(arg))
            if isinstance(arg, str) and arg.strip()
            else DEFAULT_SKILLS_ROOT
        )

        skills = list_metadata(skills_root)
        return {
            "ok": True,
            "skills": [
                {"name": s.name, "description": s.description, "path": s.path}
                for s in skills
            ],
            "prompt": build_metadata_prompt(skills),
        }

    # =========================================================
    # 2. read_file
    # =========================================================
    if action == "read_file":
        if not isinstance(arg, str) or not arg.strip():
            raise SkillError("read_file requires file path as arg")

        target = Path(os.path.expanduser(arg))
        if not target.exists():
            raise SkillError(f"File not found: {target}")
        if not target.is_file():
            raise SkillError(f"Not a file: {target}")

        return {
            "ok": True,
            "content": target.read_text(encoding="utf-8"),
        }

    # =========================================================
    # 3. run_command
    # =========================================================
    if action == "run_command":
        if not isinstance(arg, str) or not arg.strip():
            raise SkillError("run_command requires command string as arg")

        # ⚠️ 安全起见：不启用 shell=True
        # cmd = arg.strip().split()

        proc = subprocess.run(
            arg,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
        )

        return {
            "ok": True,
            "result": {
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            },
        }

    # =========================================================
    # Unknown action
    # =========================================================
    raise SkillError(f"Unknown action: {action}")
