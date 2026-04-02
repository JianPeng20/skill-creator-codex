#!/usr/bin/env python3
"""Create a portable zip archive of a skill folder.

The archive is useful for sharing or backup. For first-class Codex
distribution, wrap the skill in a plugin instead of relying on the archive
alone.
"""

from __future__ import annotations

import fnmatch
import sys
import zipfile
from pathlib import Path

from scripts.quick_validate import validate_skill


EXCLUDE_DIRS = {"__pycache__", "node_modules"}
EXCLUDE_GLOBS = {"*.pyc"}
EXCLUDE_FILES = {".DS_Store"}
ROOT_EXCLUDE_DIRS = {"evals"}


def should_exclude(rel_path: Path) -> bool:
    """Return True when a file should be skipped from the archive."""
    parts = rel_path.parts
    if any(part in EXCLUDE_DIRS for part in parts):
        return True
    if len(parts) > 1 and parts[1] in ROOT_EXCLUDE_DIRS:
        return True
    name = rel_path.name
    if name in EXCLUDE_FILES:
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in EXCLUDE_GLOBS)


def package_skill(skill_path: str | Path, output_dir: str | Path | None = None) -> Path | None:
    """Archive a skill folder into `<skill-name>.zip`."""
    skill_path = Path(skill_path).resolve()

    if not skill_path.exists():
        print(f"Error: Skill folder not found: {skill_path}")
        return None
    if not skill_path.is_dir():
        print(f"Error: Path is not a directory: {skill_path}")
        return None
    if not (skill_path / "SKILL.md").exists():
        print(f"Error: SKILL.md not found in {skill_path}")
        return None

    print("Validating skill...")
    valid, message = validate_skill(skill_path)
    if not valid:
        print(f"Validation failed: {message}")
        print("Fix the validation errors before packaging.")
        return None
    print(f"{message}\n")

    if output_dir:
        output_path = Path(output_dir).resolve()
        output_path.mkdir(parents=True, exist_ok=True)
    else:
        output_path = Path.cwd()

    archive_path = output_path / f"{skill_path.name}.zip"

    try:
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for file_path in skill_path.rglob("*"):
                if not file_path.is_file():
                    continue
                arcname = file_path.relative_to(skill_path.parent)
                if should_exclude(arcname):
                    print(f"  Skipped: {arcname}")
                    continue
                zip_file.write(file_path, arcname)
                print(f"  Added: {arcname}")

        print(f"\nCreated archive: {archive_path}")
        print("Note: this zip is for sharing or backup. For Codex UI distribution,")
        print("wrap the skill in a plugin and place it under the plugin's skills/.")
        return archive_path
    except Exception as exc:
        print(f"Error creating archive: {exc}")
        return None


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.package_skill <path/to/skill-folder> [output-directory]")
        print("\nExample:")
        print("  python -m scripts.package_skill skills/public/my-skill")
        print("  python -m scripts.package_skill skills/public/my-skill ./dist")
        sys.exit(1)

    skill_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"Packaging skill archive: {skill_path}")
    if output_dir:
        print(f"Output directory: {output_dir}")
    print()

    result = package_skill(skill_path, output_dir)
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()
