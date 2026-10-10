"""LLM_MODE=fake: deterministic agents — no key, no quota. Used for UI work, local E2E and
as the base of the test fake. It reads the same prompts Gemini would get, so the whole loop
(protocol parser, citations, sources, approval) runs exactly as in production.

The demo Supervisor delegates researcher → writer → reviewer, then answers FINAL; after
human feedback it asks the writer once more."""

import json
import re
import time

from app.domain.ports import LLMRequest, LLMResponse, TokenUsage, UserMessage

_RESULT = re.compile(r"Result from (\w+)(?: \(failed\))?:")
_SOURCE_LINE = re.compile(r"^\[(\d+)\] (.+?) — (\S+)$", re.MULTILINE)
_WIKI_BLOCK = re.compile(r'kind="wikipedia" n="(\d+)" title="([^"]*)"')
_CITE = re.compile(r"\[(\d{1,3})\]")
_SENTENCE = re.compile(r"^(\d+)\. \[cites ([\d, ]+)\] (.+)$", re.MULTILINE)
ORDER = ("researcher", "writer", "reviewer")


def _section(prompt: str, heading: str) -> str:
    part = prompt.split(f"# {heading}", 1)
    return part[1].split("\n# ", 1)[0] if len(part) == 2 else ""


def _user_task(prompt: str) -> str:
    block = _section(prompt, "User task")
    inner = re.search(r'kind="user_task">\n(.*?)\n</data', block, re.DOTALL)
    return " ".join((inner.group(1) if inner else block).split())[:120]


class DemoLLMClient:
    def __init__(self, delay_s: float = 0.0) -> None:
        self._delay = delay_s  # makes the live activity feed visible in E2E

    def generate(self, request: LLMRequest) -> LLMResponse:
        if self._delay:
            time.sleep(self._delay)
        prompt = "\n".join(m.text for m in request.messages if isinstance(m, UserMessage))
        schema = request.response_schema.__name__ if request.response_schema else None
        usage = TokenUsage(input=len(request.system + prompt) // 4, output=80)
        if schema is not None:
            data = self._review() if schema == "ReviewLLM" else self._fact_check(prompt)
            return LLMResponse(json.dumps(data), [], data, usage, "stop")
        if "You are the Supervisor" in request.system:
            text = self._supervisor(prompt)
        elif "You are the Researcher" in request.system:
            text = self._researcher(prompt)
        elif "You are the Writer" in request.system:
            text = self._writer(prompt)
        else:
            text = "Demo mode."
        return LLMResponse(text, [], None, usage, "stop")

    # ---- agents ------------------------------------------------------------------------

    def _supervisor(self, prompt: str) -> str:
        if "You have no decisions left" in prompt:
            return self._final(prompt, "No decisions left.")
        conversation = _section(prompt, "Conversation so far")
        if "Human reviewer feedback" in conversation:
            after = conversation.rsplit("Human reviewer feedback", 1)[1]
            if "Result from writer" not in after:
                return (
                    "REASON: The reviewer asked for changes.\nDELEGATE: writer\n"
                    "TASK: Revise the draft to address the human reviewer's feedback."
                )
            return self._final(prompt, "The revised draft addresses the feedback.")
        done = set(_RESULT.findall(conversation))
        for worker in ORDER:
            if worker not in done:
                task = {
                    "researcher": f"Topics: {_user_task(prompt)}\n"
                    "Find the key facts for the user task.",
                    "writer": "Write a clear answer to the user task from the research notes.",
                    "reviewer": "Review the latest draft against the task and the notes.",
                }[worker]
                return f"REASON: Next step is the {worker}.\nDELEGATE: {worker}\nTASK: {task}"
        return self._final(prompt, "The draft was reviewed and approved.")

    def _final(self, prompt: str, reason: str) -> str:
        sources = _SOURCE_LINE.findall(_section(prompt, "Sources found so far"))
        cites = " ".join(f"[{n}]" for n, _, _ in sources[:2])
        listing = "\n".join(f"{n}. {title} — {url}" for n, title, url in sources[:2])
        body = (
            f"## {_user_task(prompt) or 'Answer'}\n\n"
            f"Demo mode (LLM_MODE=fake, no Gemini call): this answer was produced by the "
            f"scripted Supervisor after its workers ran {cites}.".rstrip()
        )
        if listing:
            body += f"\n\n### Sources\n{listing}"
        return f"REASON: {reason}\nFINAL:\n{body}"

    def _researcher(self, prompt: str) -> str:
        blocks = _WIKI_BLOCK.findall(prompt)
        if not blocks:
            return (
                "UNSOURCED: notes from general knowledge, not verified against sources.\n"
                "- Demo mode: no sources were found for this assignment.\nGaps: everything."
            )
        lines = [f"- {title} is relevant to the task [{n}]." for n, title in blocks]
        return "## Notes\n" + "\n".join(lines) + "\nGaps: none (demo mode)."

    def _writer(self, prompt: str) -> str:
        notes = _section(prompt, "Research notes")
        cites = sorted({int(n) for n in _CITE.findall(notes)})[:3]
        marks = " ".join(f"[{n}]" for n in cites)
        return (
            f"## {_user_task(prompt) or 'Answer'}\n\n"
            f"Demo draft: the research notes cover the main points of this task {marks}.".strip()
            + "\n\nThis text was written by the demo Writer (no Gemini call)."
        )

    def _review(self) -> dict:
        return {
            "verdict": "approve",
            "issues": [{"severity": "low", "text": "Demo review: a short example would help."}],
            "balance_flags": [],
        }

    def _fact_check(self, prompt: str) -> dict:
        claims = [
            {
                "sentence": s.strip(),
                "status": "supported",
                "source_n": int(ns.split(",")[0]),
                "note": "",
            }
            for _, ns, s in _SENTENCE.findall(prompt)
        ]
        return {"claims": claims[:12]}
