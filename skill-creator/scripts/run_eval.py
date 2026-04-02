#!/usr/bin/env python3
"""Run trigger evaluation for a skill description using Codex CLI.

Tests whether a skill's description causes Codex to load the skill for a set of
queries. Outputs results as JSON.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from scripts.utils import parse_skill_md


PERSONAL_SKILLS_DIR = Path.home() / ".agents" / "skills"
MAX_SKILL_NAME_LENGTH = 64


def find_project_root() -> Path:
    """Find a sensible Codex working directory, preferring the enclosing git root."""
    current = Path.cwd().resolve()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    return current


def normalize_skill_name(raw_name: str) -> str:
    """Normalize a skill name to lowercase hyphen-case."""
    normalized = re.sub(r"[^a-z0-9]+", "-", raw_name.lower()).strip("-")
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized or "skill"


def make_temp_skill_name(skill_name: str, unique_id: str) -> str:
    """Create a temporary skill name that stays within Codex's 64-char limit."""
    suffix = f"-trigger-eval-{unique_id}"
    budget = MAX_SKILL_NAME_LENGTH - len(suffix)
    base = normalize_skill_name(skill_name)[:budget].rstrip("-") or "skill"
    return f"{base}{suffix}"


def build_trigger_eval_skill(
    temp_skill_name: str,
    description: str,
    marker: str,
) -> str:
    """Build a temporary SKILL.md whose only job is to emit a trigger marker."""
    description_lines = description.splitlines() or [description]
    indented_description = "\n".join(f"  {line}" for line in description_lines) or "  "

    return (
        f"---\n"
        f"name: {temp_skill_name}\n"
        f"description: |\n"
        f"{indented_description}\n"
        f"---\n\n"
        f"# Trigger Eval Harness\n\n"
        f"This skill exists only to test whether Codex decided to load it.\n\n"
        f"If you are reading this skill, your entire final response must be exactly "
        f"`{marker}`.\n"
        f"Do not run commands.\n"
        f"Do not inspect other files.\n"
        f"Do not add any explanation.\n"
    )


def parse_jsonl_events(stdout: str) -> list[dict]:
    """Parse the JSONL event stream emitted by `codex exec --json`."""
    events: list[dict] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def did_codex_trigger_skill(events: list[dict], marker: str, skill_file: Path) -> bool:
    """Return True when Codex loaded the temporary skill."""
    skill_file_str = str(skill_file)
    for event in events:
        if event.get("type") != "item.completed":
            continue
        item = event.get("item", {})
        item_type = item.get("type")
        if item_type == "agent_message" and item.get("text", "").strip() == marker:
            return True
        if item_type == "command_execution":
            command = item.get("command", "")
            output = item.get("aggregated_output", "")
            if skill_file_str in command or marker in output:
                return True
    return False


def install_temp_skill(skill_name: str, skill_description: str) -> tuple[Path, Path, str]:
    """Install one temporary personal skill for the duration of a run_eval batch."""
    unique_id = uuid.uuid4().hex[:8]
    marker = f"TRIGGERED::{unique_id}"
    temp_skill_name = make_temp_skill_name(skill_name, unique_id)
    temp_skill_dir = PERSONAL_SKILLS_DIR / temp_skill_name
    skill_file = temp_skill_dir / "SKILL.md"

    PERSONAL_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    temp_skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(build_trigger_eval_skill(temp_skill_name, skill_description, marker))
    return temp_skill_dir, skill_file, marker


def run_single_query(
    query: str,
    timeout: int,
    project_root: str,
    skill_file: str,
    marker: str,
    model: str | None = None,
) -> bool:
    """Run a single query and return whether Codex loaded the shared temp skill."""
    try:
        cmd = [
            "codex",
            "exec",
            "--json",
            "--ephemeral",
            "--skip-git-repo-check",
            "-C",
            project_root,
            "-s",
            "read-only",
            query,
        ]
        if model:
            cmd.extend(["--model", model])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        events = parse_jsonl_events(result.stdout)
        return did_codex_trigger_skill(events, marker, Path(skill_file))
    except subprocess.TimeoutExpired:
        return False


def run_eval(
    eval_set: list[dict],
    skill_name: str,
    description: str,
    num_workers: int,
    timeout: int,
    project_root: Path,
    runs_per_query: int = 1,
    trigger_threshold: float = 0.5,
    model: str | None = None,
) -> dict:
    """Run the full eval set and return results."""
    results = []

    temp_skill_dir, skill_file, marker = install_temp_skill(skill_name, description)

    try:
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            future_to_info = {}
            for item in eval_set:
                for run_idx in range(runs_per_query):
                    future = executor.submit(
                        run_single_query,
                        item["query"],
                        timeout,
                        str(project_root),
                        str(skill_file),
                        marker,
                        model,
                    )
                    future_to_info[future] = (item, run_idx)

            query_triggers: dict[str, list[bool]] = {}
            query_items: dict[str, dict] = {}
            for future in as_completed(future_to_info):
                item, _ = future_to_info[future]
                query = item["query"]
                query_items[query] = item
                query_triggers.setdefault(query, [])
                try:
                    query_triggers[query].append(future.result())
                except Exception as exc:
                    print(f"Warning: query failed: {exc}", file=sys.stderr)
                    query_triggers[query].append(False)
    finally:
        shutil.rmtree(temp_skill_dir, ignore_errors=True)

    for query, triggers in query_triggers.items():
        item = query_items[query]
        trigger_rate = sum(triggers) / len(triggers)
        should_trigger = item["should_trigger"]
        did_pass = (
            trigger_rate >= trigger_threshold
            if should_trigger
            else trigger_rate < trigger_threshold
        )
        results.append(
            {
                "query": query,
                "should_trigger": should_trigger,
                "trigger_rate": trigger_rate,
                "triggers": sum(triggers),
                "runs": len(triggers),
                "pass": did_pass,
            }
        )

    passed = sum(1 for result in results if result["pass"])
    total = len(results)

    return {
        "skill_name": skill_name,
        "description": description,
        "results": results,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run trigger evaluation for a skill description"
    )
    parser.add_argument("--eval-set", required=True, help="Path to eval set JSON file")
    parser.add_argument("--skill-path", required=True, help="Path to skill directory")
    parser.add_argument("--description", default=None, help="Override description to test")
    parser.add_argument(
        "--num-workers", type=int, default=10, help="Number of parallel workers"
    )
    parser.add_argument(
        "--timeout", type=int, default=30, help="Timeout per query in seconds"
    )
    parser.add_argument(
        "--runs-per-query", type=int, default=3, help="Number of runs per query"
    )
    parser.add_argument(
        "--trigger-threshold", type=float, default=0.5, help="Trigger rate threshold"
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model to use for `codex exec` (default: current Codex config)",
    )
    parser.add_argument("--verbose", action="store_true", help="Print progress to stderr")
    args = parser.parse_args()

    eval_set = json.loads(Path(args.eval_set).read_text())
    skill_path = Path(args.skill_path)

    if not (skill_path / "SKILL.md").exists():
        print(f"Error: No SKILL.md found at {skill_path}", file=sys.stderr)
        sys.exit(1)

    name, original_description, _ = parse_skill_md(skill_path)
    description = args.description or original_description
    project_root = find_project_root()

    if args.verbose:
        print(f"Evaluating: {description}", file=sys.stderr)

    output = run_eval(
        eval_set=eval_set,
        skill_name=name,
        description=description,
        num_workers=args.num_workers,
        timeout=args.timeout,
        project_root=project_root,
        runs_per_query=args.runs_per_query,
        trigger_threshold=args.trigger_threshold,
        model=args.model,
    )

    if args.verbose:
        summary = output["summary"]
        print(
            f"Results: {summary['passed']}/{summary['total']} passed",
            file=sys.stderr,
        )
        for result in output["results"]:
            status = "PASS" if result["pass"] else "FAIL"
            rate_str = f"{result['triggers']}/{result['runs']}"
            print(
                f"  [{status}] rate={rate_str} expected={result['should_trigger']}: "
                f"{result['query'][:70]}",
                file=sys.stderr,
            )

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
