"""
ARIEXUS Runtime – orchestrates intent parsing and task-graph execution.
"""

from pathlib import Path
from typing import Any, Dict, Optional

from arxus.models import TaskGraph
from arxus.executor import TaskExecutor
from arxus.approval import ApprovalService
from arxus.audit import AuditLogger
from arxus.tools.base import BaseTool
from arxus.intent import IntentParser


class ARIEXUSRuntime:
    def __init__(
        self,
        tools: Dict[str, BaseTool],
        approval_service: ApprovalService,
        audit_logger: AuditLogger,
        workspace_root: str = "./workspace",
        llm_provider: Optional[str] = None,
        llm_model: Optional[str] = None,
    ):
        self.tools = tools
        self.approval_service = approval_service
        self.audit_logger = audit_logger
        self.workspace_root = workspace_root
        self.executor = TaskExecutor(tools, approval_service, audit_logger)
        self.intent_parser = IntentParser(
            provider=llm_provider,
            model=llm_model,
            fallback_to_keywords=True,
        )

    async def parse_intent_to_task_graph(self, intent: str) -> TaskGraph:
        """
        Convert natural language into a typed TaskGraph.
        Uses LLM (Ollama / OpenAI / xAI) with automatic keyword fallback.
        """
        return self.intent_parser.parse(intent)

    async def execute_task_graph(self, graph: TaskGraph) -> Dict[str, Any]:
        return await self.executor.execute_task_graph(graph)
