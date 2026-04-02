#!/usr/bin/env python3
"""Improve a skill description based on eval results.

Takes eval results (from run_eval.py) and generates an improved description by
calling `codex exec` as a subprocess.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.utils import parse_skill_md


def _call_codex(prompt: str, model: str | None, timeout: int = 300) -> str:
    """Run `codex exec` with the prompt on stdin and return the final message."""
    with tempfile.TemporaryDirectory(prefix="skill-creator-improve-") as tmpdir:
        output_path = Path(tmpdir) / "last_message.txt"
        cmd = [
            "codex",
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "-C",
            tmpdir,
            "-s",
            "read-only",
            "-o",
            str(output_path),
            "-",
        ]
        if model:
            cmd.extend(["--model", model])

        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"codex exec exited {result.returncode}\nstderr: {result.stderr}"
            )

        if output_path.exists():
            return output_path.read_text()
        return result.stdout


def improve_description(
    skill_name: str,
    skill_content: str,
    current_description: str,
    eval_results: dict,
    history: list[dict],
    model: str,
    test_results: dict | None = None,
    log_dir: Path | None = None,
    iteration: int | None = None,
) -> str:
    """Call Codex to improve the description based on eval results."""
    failed_triggers = [
        result
        for result in eval_results["results"]
        if result["should_trigger"] and not result["pass"]
    ]
    false_triggers = [
        result
        for result in eval_results["results"]
        if not result["should_trigger"] and not result["pass"]
    ]

    train_score = (
        f"{eval_results['summary']['passed']}/{eval_results['summary']['total']}"
    )
    if test_results:
        test_score = (
            f"{test_results['summary']['passed']}/{test_results['summary']['total']}"
        )
        scores_summary = f"Train: {train_score}, Test: {test_score}"
    else:
        scores_summary = f"Train: {train_score}"

    prompt = f"""You are optimizing a skill description for a Codex skill called "{skill_name}".
A Codex skill is a folder with a SKILL.md frontmatter (`name` + `description`)
and a markdown body. Codex decides whether to load the skill primarily from the
skill's name and description, then reads the body only after the skill is chosen.

Here's the current description:
<current_description>
"{current_description}"
</current_description>

Current scores ({scores_summary}):
<scores_summary>
"""
    if failed_triggers:
        prompt += "FAILED TO TRIGGER (should have triggered but didn't):\n"
        for result in failed_triggers:
            prompt += (
                f'  - "{result["query"]}" '
                f'(triggered {result["triggers"]}/{result["runs"]} times)\n'
            )
        prompt += "\n"

    if false_triggers:
        prompt += "FALSE TRIGGERS (triggered but should not have):\n"
        for result in false_triggers:
            prompt += (
                f'  - "{result["query"]}" '
                f'(triggered {result["triggers"]}/{result["runs"]} times)\n'
            )
        prompt += "\n"

    if history:
        prompt += (
            "PREVIOUS ATTEMPTS (do not repeat these verbatim; try a structurally "
            "different framing):\n\n"
        )
        for item in history:
            train_s = (
                f"{item.get('train_passed', item.get('passed', 0))}/"
                f"{item.get('train_total', item.get('total', 0))}"
            )
            test_s = (
                f"{item.get('test_passed', '?')}/{item.get('test_total', '?')}"
                if item.get("test_passed") is not None
                else None
            )
            score_str = f"train={train_s}" + (f", test={test_s}" if test_s else "")
            prompt += f'<attempt {score_str}>\n'
            prompt += f'Description: "{item["description"]}"\n'
            if "results" in item:
                prompt += "Train results:\n"
                for result in item["results"]:
                    status = "PASS" if result["pass"] else "FAIL"
                    prompt += (
                        f'  [{status}] "{result["query"][:80]}" '
                        f'(triggered {result["triggers"]}/{result["runs"]})\n'
                    )
            if item.get("note"):
                prompt += f'Note: {item["note"]}\n'
            prompt += "</attempt>\n\n"

    prompt += f"""</scores_summary>

Skill content (for context on what the skill does):
<skill_content>
{skill_content}
</skill_content>

Write a new description that is more likely to trigger correctly in Codex.
Generalize from the failures instead of overfitting to these exact prompts.

Constraints:
- Focus on user intent and when the skill should be used.
- Prefer "Use this skill when..." phrasing.
- Keep it distinctive so Codex can tell it apart from adjacent skills.
- Keep it concise: about 100-200 words max.
- There is a hard limit of 1024 characters, so stay comfortably under it.

Please respond with only the new description text inside <new_description>
tags, with no extra commentary."""

    text = _call_codex(prompt, model)

    match = re.search(r"<new_description>(.*?)</new_description>", text, re.DOTALL)
    description = match.group(1).strip().strip('"') if match else text.strip().strip('"')

    transcript: dict = {
        "iteration": iteration,
        "prompt": prompt,
        "response": text,
        "parsed_description": description,
        "char_count": len(description),
        "over_limit": len(description) > 1024,
    }

    if len(description) > 1024:
        shorten_prompt = (
            f"{prompt}\n\n"
            f"---\n\n"
            f"A previous attempt produced this description, which at "
            f"{len(description)} characters is over the 1024-character hard limit:\n\n"
            f'"{description}"\n\n'
            f"Rewrite it to be under 1024 characters while keeping the most "
            f"important trigger words and intent coverage. Respond with only "
            f"the new description in <new_description> tags."
        )
        shorten_text = _call_codex(shorten_prompt, model)
        match = re.search(
            r"<new_description>(.*?)</new_description>",
            shorten_text,
            re.DOTALL,
        )
        shortened = (
            match.group(1).strip().strip('"')
            if match
            else shorten_text.strip().strip('"')
        )

        transcript["rewrite_prompt"] = shorten_prompt
        transcript["rewrite_response"] = shorten_text
        transcript["rewrite_description"] = shortened
        transcript["rewrite_char_count"] = len(shortened)
        description = shortened

    transcript["final_description"] = description

    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"improve_iter_{iteration or 'unknown'}.json"
        log_file.write_text(json.dumps(transcript, indent=2))

    return description


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Improve a skill description based on eval results"
    )
    parser.add_argument(
        "--eval-results", required=True, help="Path to eval results JSON (from run_eval.py)"
    )
    parser.add_argument("--skill-path", required=True, help="Path to skill directory")
    parser.add_argument(
        "--history", default=None, help="Path to history JSON (previous attempts)"
    )
    parser.add_argument("--model", required=True, help="Model for improvement")
    parser.add_argument("--verbose", action="store_true", help="Print thinking to stderr")
    args = parser.parse_args()

    skill_path = Path(args.skill_path)
    if not (skill_path / "SKILL.md").exists():
        print(f"Error: No SKILL.md found at {skill_path}", file=sys.stderr)
        sys.exit(1)

    eval_results = json.loads(Path(args.eval_results).read_text())
    history = json.loads(Path(args.history).read_text()) if args.history else []

    name, _, content = parse_skill_md(skill_path)
    current_description = eval_results["description"]

    if args.verbose:
        print(f"Current: {current_description}", file=sys.stderr)
        print(
            f"Score: {eval_results['summary']['passed']}/"
            f"{eval_results['summary']['total']}",
            file=sys.stderr,
        )

    new_description = improve_description(
        skill_name=name,
        skill_content=content,
        current_description=current_description,
        eval_results=eval_results,
        history=history,
        model=args.model,
    )

    if args.verbose:
        print(f"Improved: {new_description}", file=sys.stderr)

    output = {
        "description": new_description,
        "history": history
        + [
            {
                "description": current_description,
                "passed": eval_results["summary"]["passed"],
                "failed": eval_results["summary"]["failed"],
                "total": eval_results["summary"]["total"],
                "results": eval_results["results"],
            }
        ],
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
