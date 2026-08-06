"""
LLM Intent Parser – converts natural language into a typed TaskGraph.
Supports:
  • Ollama (default, free, local)
  • OpenAI-compatible APIs (OpenAI, xAI/Grok, etc.)
Falls back to keyword parser if LLM is unavailable.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from arxus.models import TaskGraph, TaskStep, StepKind, RiskLevel, CompensationType


SYSTEM_PROMPT = """You are the intent parser for ARIEXUS, a secure agent runtime.
Convert the user's natural-language request into a TaskGraph JSON object.

Available tools and capabilities:

1. filesystem
   - filesystem.list   → input: {"operation":"list","path":"<dir>"}
   - filesystem.read   → input: {"operation":"read","path":"<file>"}
   - filesystem.write  → input: {"operation":"write","path":"<file>","content":"<text>"}
   - filesystem.info   → input: {"operation":"info","path":"<path>"}

2. terminal
   - terminal.run      → input: {"command":"<cmd>","args":["..."],"cwd":"."}
     Allowed commands only: git, ls, pwd, echo, cat, python, python3, pip, npm, pytest, mkdir, touch

Rules:
- Prefer the minimum number of steps that achieve the goal.
- filesystem.write and any terminal command that mutates state → risk "medium" or "high" and requires_approval = true.
- filesystem.read / list / info → risk "low", requires_approval = false.
- Always return ONLY a valid JSON object matching this schema (no markdown, no explanation):

{
  "goal": "short description of what we are doing",
  "steps": [
    {
      "kind": "tool",
      "capability": "filesystem.list",
      "input": {"operation": "list", "path": "."},
      "risk": "low",
      "requires_approval": false,
      "requires_approval_reason": null,
      "cost_estimate": 0.0,
      "timeout_seconds": 10,
      "max_retries": 1
    }
  ],
  "success_criteria": ["list of strings describing success"],
  "cost_budget": 5.0
}

Risk values: "low" | "medium" | "high" | "critical"
kind is always "tool" for now.
"""


def _keyword_fallback(intent: str) -> TaskGraph:
    lower = intent.lower()

    if any(w in lower for w in ("list", "ls", "show files", "directory")):
        path = "."
        if " of " in lower:
            path = intent.split(" of ")[-1].strip(". ,!?;: ") or "."
        return TaskGraph(
            goal=f"List directory: {path}",
            steps=[
                TaskStep(
                    kind=StepKind.TOOL,
                    capability="filesystem.list",
                    input={"operation": "list", "path": path},
                    risk=RiskLevel.LOW,
                )
            ],
        )

    if "read" in lower:
        filename = None
        for word in intent.split():
            if "." in word and not word.startswith("http"):
                filename = word.strip(". ,!?;:\"'")
                break
        if filename:
            return TaskGraph(
                goal=f"Read file {filename}",
                steps=[
                    TaskStep(
                        kind=StepKind.TOOL,
                        capability="filesystem.read",
                        input={"operation": "read", "path": filename},
                        risk=RiskLevel.LOW,
                    )
                ],
            )

    if any(w in lower for w in ("write", "create", "make a file", "save")):
        content = ""
        quoted = re.findall(r'[\"\']([^\"\']*)[\"\']', intent)
        if quoted:
            content = quoted[0]
        filename = "new_file.txt"
        for word in intent.split():
            if any(word.endswith(ext) for ext in (".txt", ".md", ".json", ".py", ".yml", ".yaml")):
                filename = word.strip(". ,!?;:\"'")
                break
        return TaskGraph(
            goal=f"Write file {filename}",
            steps=[
                TaskStep(
                    kind=StepKind.TOOL,
                    capability="filesystem.write",
                    input={
                        "operation": "write",
                        "path": filename,
                        "content": content or "# Created by ARIEXUS\n",
                    },
                    risk=RiskLevel.MEDIUM,
                    requires_approval=True,
                    requires_approval_reason=f"Creating/modifying file: {filename}",
                )
            ],
        )

    return TaskGraph(
        goal=f"Echo: {intent}",
        steps=[
            TaskStep(
                kind=StepKind.TOOL,
                capability="terminal.run",
                input={"command": "echo", "args": [intent]},
                risk=RiskLevel.LOW,
            )
        ],
    )


def _parse_llm_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    if "```" in text:
        start = text.find("```")
        end = text.rfind("```")
        if end > start:
            block = text[start:end]
            block = re.sub(r"^```(?:json)?\s*", "", block)
            text = block
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        raise ValueError("No JSON object found in LLM response")
    return json.loads(text[start:end])


def _dict_to_task_graph(data: Dict[str, Any]) -> TaskGraph:
    steps: List[TaskStep] = []
    for s in data.get("steps", []):
        risk_str = str(s.get("risk", "low")).lower()
        try:
            risk = RiskLevel(risk_str)
        except ValueError:
            risk = RiskLevel.MEDIUM

        steps.append(
            TaskStep(
                kind=StepKind.TOOL,
                capability=s.get("capability", "terminal.run"),
                input=s.get("input", {}),
                risk=risk,
                requires_approval=bool(s.get("requires_approval", False)),
                requires_approval_reason=s.get("requires_approval_reason"),
                cost_estimate=float(s.get("cost_estimate", 0.0)),
                timeout_seconds=int(s.get("timeout_seconds", 30)),
                max_retries=int(s.get("max_retries", 1)),
            )
        )

    if not steps:
        raise ValueError("LLM returned empty steps")

    return TaskGraph(
        goal=data.get("goal", "LLM-generated task"),
        steps=steps,
        success_criteria=data.get("success_criteria", []),
        cost_budget=float(data.get("cost_budget", 5.0)),
    )


def _call_ollama(prompt: str, model: str = "llama3.2") -> str:
    import ollama
    resp = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        options={"temperature": 0.1},
    )
    return resp["message"]["content"]


def _call_openai_compatible(prompt: str, model: str, base_url: Optional[str], api_key: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        max_tokens=800,
    )
    return resp.choices[0].message.content or ""


class IntentParser:
    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        fallback_to_keywords: bool = True,
    ):
        self.provider = (provider or os.getenv("ARX_LLM_PROVIDER", "ollama")).lower()
        self.model = model or os.getenv("ARX_LLM_MODEL")
        self.fallback_to_keywords = fallback_to_keywords

        if self.provider == "ollama":
            self.model = self.model or "llama3.2"
        elif self.provider == "openai":
            self.model = self.model or "gpt-4o-mini"
        elif self.provider == "xai":
            self.model = self.model or "grok-4"
        else:
            self.model = self.model or "llama3.2"

    def parse(self, intent: str) -> TaskGraph:
        try:
            if self.provider == "ollama":
                raw = _call_ollama(intent, self.model)
            elif self.provider == "openai":
                key = os.getenv("OPENAI_API_KEY")
                if not key:
                    raise RuntimeError("OPENAI_API_KEY not set")
                raw = _call_openai_compatible(intent, self.model, None, key)
            elif self.provider == "xai":
                key = os.getenv("XAI_API_KEY")
                if not key:
                    raise RuntimeError("XAI_API_KEY not set")
                raw = _call_openai_compatible(
                    intent, self.model, "https://api.x.ai/v1", key
                )
            else:
                raise ValueError(f"Unknown provider: {self.provider}")

            data = _parse_llm_json(raw)
            return _dict_to_task_graph(data)

        except Exception as e:
            if self.fallback_to_keywords:
                print(f"[intent] LLM failed ({e}) → keyword fallback")
                return _keyword_fallback(intent)
            raise
