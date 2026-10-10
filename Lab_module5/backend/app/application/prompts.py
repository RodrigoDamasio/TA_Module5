"""Prompt library (app/prompts, versioned by the VERSION file) — the Labs 2-4 loader.

Every request is assembled from layers:
    system = base.md ← {persona} (supervisor.md or workers/<name>.md) ← {canary}
    user   = <agent>_task.md ← the agent's inputs (fenced untrusted text)
"""

import math
import re
from functools import cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def fill(template: str, **values: object) -> str:
    """Replace only the given {placeholders}; other braces stay as they are. One pass, so a
    value that contains '{task}' is never substituted again."""
    return _PLACEHOLDER.sub(
        lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), template
    )


def placeholders(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text))


def estimate_tokens(text: str) -> int:
    """~3.5 characters per token (conservative for budgets)."""
    return math.ceil(len(text) / 3.5)


class PromptLibrary:
    def __init__(self, root: Path = PROMPTS_DIR) -> None:
        self._root = root

    @cache  # noqa: B019 — one library per process; files never change at runtime
    def read(self, name: str) -> str:
        return (self._root / name).read_text().strip()

    @property
    def version(self) -> str:
        return self.read("VERSION")

    def system(self, persona: str, canary: str) -> str:
        return fill(self.read("base.md"), persona=persona, canary=canary)

    # ---- supervisor ------------------------------------------------------------------

    def supervisor_system(
        self, worker_list: str, parallel_rule: str, fact_check_hint: str, canary: str
    ) -> str:
        persona = fill(
            self.read("supervisor.md"),
            worker_list=worker_list,
            parallel_rule=f"\n{parallel_rule}\n" if parallel_rule else "",
            fact_check_hint=fact_check_hint,
        )
        return self.system(persona, canary)

    def supervisor_task(self, **values: object) -> str:
        return fill(self.read("supervisor_task.md"), **values)

    def supervisor_repair(self, parser_error: str) -> str:
        return fill(self.read("supervisor_repair.md"), parser_error=parser_error)

    def supervisor_forced(self) -> str:
        return self.read("supervisor_forced.md")

    # ---- workers -----------------------------------------------------------------------

    def worker_system(self, name: str, canary: str) -> str:
        return self.system(self.read(f"workers/{name}.md"), canary)

    def worker_task(self, template: str, **values: object) -> str:
        return fill(self.read(f"workers/{template}.md"), **values)

    def repair(self, validation_errors: str) -> str:
        return fill(self.read("repair.md"), validation_errors=validation_errors)
