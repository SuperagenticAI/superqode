"""
ACP Runner - Execute QE roles using ACP-compatible agents.

Uses the existing AgentStreamClient to communicate with coding agents
like OpenCode for AI-powered quality engineering analysis.

Features:
- Real-time streaming of agent analysis
- Structured finding extraction from agent output
- Support for OpenCode free models
- Integration with QE noise controls
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import logging
import shutil

from superqode.agent_stream import (
    AgentStreamClient,
    StreamEvent,
    StreamEventType,
    StreamMessage,
    StreamToolCall,
)

logger = logging.getLogger(__name__)


# Default OpenCode command (same as TUI uses)
OPENCODE_COMMAND = "opencode run --format json"

# Mapping from QE role names to OpenCode agent names
QE_ROLE_TO_OPENCODE_AGENT = {
    # Execution roles (not ACP-driven, but keep mapping for consistency)
    "smoke_tester": "deployment-readiness",
    "sanity_tester": "deployment-readiness",
    "regression_tester": "code-complexity",
    # Detection roles
    "unit_tester": "mutation-tester",
    "api_tester": "contract-tester",
    "security_tester": "mutation-tester",
    "performance_tester": "code-complexity",
    "e2e_tester": "visual-tester",
    # Heuristic role
    "fullstack": "mutation-tester",
}


def get_opencode_agent_for_role(role_name: str) -> str:
    """Map QE role name to appropriate OpenCode agent."""
    return QE_ROLE_TO_OPENCODE_AGENT.get(role_name, "mutation-tester")  # Default fallback


@dataclass
class FixVerification:
    """Verification results for a suggested fix."""

    fix_applied: bool = False
    tests_run: List[str] = field(default_factory=list)
    tests_passed: int = 0
    tests_total: int = 0
    fix_verified: bool = False
    outcome: str = ""
    is_improvement: bool = False


@dataclass
class ACPFinding:
    """A finding extracted from ACP agent output."""

    id: str
    severity: str  # critical, high, medium, low, info
    title: str
    description: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    evidence: Optional[str] = None
    suggested_fix: Optional[str] = None
    confidence: float = 0.8
    category: str = ""

    # Fix verification data (populated when allow_suggestions is enabled)
    fix_verification: Optional[FixVerification] = None
    patch_file: Optional[str] = None  # Path to saved patch file

    @property
    def has_verified_fix(self) -> bool:
        """Check if this finding has a verified fix."""
        return (
            self.fix_verification is not None
            and self.fix_verification.fix_verified
            and self.fix_verification.is_improvement
        )


@dataclass
class ACPRunnerConfig:
    """Configuration for ACP runner."""

    # Agent command (default: opencode acp)
    agent_command: str = OPENCODE_COMMAND

    # Model to use (for agents that support model selection)
    model: Optional[str] = None

    # Timeout in seconds
    timeout_seconds: int = 300

    # Auto-approve file operations
    auto_approve: bool = True

    # Verbose output
    verbose: bool = False

    # Callback for streaming events
    on_event: Optional[Callable[[StreamEvent], None]] = None

    # Suggestion mode settings
    allow_suggestions: bool = False  # When True, ask agent to generate fixes
    verify_fixes: bool = True  # Run verification on suggested fixes
    max_fix_attempts: int = 3  # Max attempts per issue


@dataclass
class ACPRunnerResult:
    """Result from ACP runner execution."""

    success: bool
    findings: List[ACPFinding]
    agent_output: str
    tool_calls: List[Dict[str, Any]]
    duration_seconds: float
    errors: List[str]


class ACPQERunner:
    """
    Runs QE analysis using an ACP-compatible coding agent.

    Connects to agents like OpenCode and sends QE-specific prompts
    to analyze code for issues, then extracts structured findings
    from the agent's output.
    """

    def __init__(
        self,
        project_root: Path,
        config: Optional[ACPRunnerConfig] = None,
    ):
        self.project_root = project_root.resolve()
        self.config = config or ACPRunnerConfig()

        self._client: Optional[AgentStreamClient] = None
        self._collected_output: str = ""
        self._collected_thoughts: str = ""
        self._tool_calls: List[Dict[str, Any]] = []
        self._findings: List[ACPFinding] = []
        self._finding_counter = 0

    async def run(self, prompt: str, role_name: str = "qe") -> ACPRunnerResult:
        """
        Run the QE analysis with the given prompt using OpenCode subprocess.

        Args:
            prompt: The QE analysis prompt to send to the agent
            role_name: Name of the QE role (for finding IDs)

        Returns:
            ACPRunnerResult with findings and agent output
        """
        start_time = datetime.now()
        errors = []
        agent_logs = []
        collected_output = ""
        tool_calls = []

        # Check if opencode is available
        if not self._check_agent_available():
            return ACPRunnerResult(
                success=False,
                findings=[],
                agent_output="",
                tool_calls=[],
                duration_seconds=0.0,
                errors=["OpenCode not found. Install with: npm i -g opencode-ai"],
            )

        agent_logs.append(
            f"[{start_time.strftime('%H:%M:%S')}] Starting OpenCode analysis for {role_name}"
        )
        agent_logs.append(
            f"[{start_time.strftime('%H:%M:%S')}] Command: {self._build_agent_command(role_name)}"
        )

        if self.config.verbose:
            print(f"🤖 Starting {role_name} analysis with OpenCode...")

        try:
            # Build the command with appropriate agent
            cmd_parts = self._build_agent_command(role_name).split()
            cmd = cmd_parts + [prompt]

            agent_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] Executing: {' '.join(cmd)}")

            if self.config.verbose:
                model_info = f" using {self.config.model}" if self.config.model else ""
                print(f"🔧 Running OpenCode{model_info} for {role_name} analysis...")

            # Run OpenCode as subprocess with memory limits for performance
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(self.project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=50 * 1024 * 1024,  # 50MB memory limit for better performance
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )

            agent_logs.append(
                f"[{datetime.now().strftime('%H:%M:%S')}] OpenCode process started (PID: {process.pid})"
            )

            if self.config.verbose:
                print(f"⚙️  OpenCode process started (PID: {process.pid})")
                print(f"⏳ Analyzing codebase... (timeout: {self.config.timeout_seconds}s)")

            try:
                # Stream stdout/stderr in real-time while collecting output
                stdout_chunks = []
                stderr_chunks = []
                last_heartbeat = datetime.now()
                heartbeat_interval = 10.0  # Show heartbeat every 10 seconds

                async def stream_output(stream, chunks, prefix="", is_stderr=False):
                    """Stream output in real-time."""
                    while True:
                        chunk = await stream.read(8192)  # Read 8KB at a time
                        if not chunk:
                            break
                        chunks.append(chunk)
                        if self.config.verbose:
                            try:
                                text = chunk.decode("utf-8", errors="replace").rstrip()
                                if text:
                                    # Filter out verbose JSON lines (like step_finish, step_start events)
                                    for line in text.split("\n"):
                                        if line.strip():
                                            # Skip JSON event lines that are too verbose
                                            line_stripped = line.strip()
                                            # Only show if it's not a JSON event line or if it's an error
                                            if (
                                                not line_stripped.startswith('{"type":"')
                                                or "error" in line_stripped.lower()
                                                or is_stderr
                                            ):
                                                print(f"  {prefix}{line}")
                            except Exception:
                                pass

                async def show_heartbeat():
                    """Show periodic heartbeat with varied QA-related messages."""
                    start_time = datetime.now()
                    message_index = 0

                    # Varied QA-related messages with emojis
                    qa_messages = [
                        ("🔍", "Analyzing code quality..."),
                        ("🧪", "Running test suites..."),
                        ("🔐", "Scanning for security vulnerabilities..."),
                        ("⚡", "Checking performance issues..."),
                        ("📊", "Evaluating code metrics..."),
                        ("🛡️", "Validating code safety..."),
                        ("🎯", "Identifying code issues..."),
                        ("📝", "Reviewing code patterns..."),
                        ("🔎", "Inspecting code structure..."),
                        ("🧩", "Analyzing code complexity..."),
                        ("✅", "Verifying code standards..."),
                        ("🚨", "Detecting potential bugs..."),
                        ("🔧", "Examining code quality..."),
                        ("📈", "Assessing code health..."),
                        ("🎨", "Reviewing code style..."),
                        ("🔬", "Testing code functionality..."),
                        ("📋", "Checking code compliance..."),
                        ("🔄", "Running quality checks..."),
                        ("💡", "Analyzing best practices..."),
                        ("🌐", "Evaluating API quality..."),
                    ]

                    while True:
                        await asyncio.sleep(heartbeat_interval)
                        elapsed = (datetime.now() - start_time).total_seconds()
                        elapsed_str = f"{int(elapsed)}s"

                        # Cycle through messages
                        emoji, message = qa_messages[message_index % len(qa_messages)]
                        message_index += 1

                        # Always show heartbeat for user engagement
                        print(f"  {emoji} {message} ({elapsed_str} elapsed)")
                        agent_logs.append(
                            f"[{datetime.now().strftime('%H:%M:%S')}] Heartbeat: {message} ({elapsed_str} elapsed)"
                        )

                # Create tasks for streaming and heartbeat
                stdout_task = asyncio.create_task(
                    stream_output(process.stdout, stdout_chunks, prefix="[stdout] ")
                )
                stderr_task = asyncio.create_task(
                    stream_output(process.stderr, stderr_chunks, prefix="[stderr] ", is_stderr=True)
                )
                heartbeat_task = asyncio.create_task(show_heartbeat())

                # Wait for process to complete with timeout
                try:
                    # Wait for both streams to finish reading and process to complete
                    async def wait_for_completion():
                        # Wait for streams to finish
                        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
                        # Wait for process to finish
                        return await process.wait()

                    return_code = await asyncio.wait_for(
                        wait_for_completion(), timeout=self.config.timeout_seconds
                    )
                    heartbeat_task.cancel()  # Stop heartbeat
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass
                except asyncio.TimeoutError:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass
                    # Kill process on timeout
                    try:
                        process.kill()
                        await process.wait()
                    except Exception:
                        pass
                    raise asyncio.TimeoutError("Process timed out")

                # Combine chunks
                stdout = b"".join(stdout_chunks)
                stderr = b"".join(stderr_chunks)

                agent_logs.append(
                    f"[{datetime.now().strftime('%H:%M:%S')}] Process completed with return code: {return_code}"
                )

                if return_code == 0:
                    agent_logs.append(
                        f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Analysis completed successfully"
                    )

                    if self.config.verbose:
                        print(f"✅ {role_name} analysis completed successfully")

                    # Parse JSON output
                    try:
                        output_text = stdout.decode("utf-8", errors="replace")
                        collected_output = output_text

                        # Try to parse as a single JSON object
                        try:
                            json_data = json.loads(output_text)
                            agent_logs.append(
                                f"[{datetime.now().strftime('%H:%M:%S')}] Parsed JSON response"
                            )

                            # Extract findings from JSON structure
                            self._findings = self._extract_findings_from_json(json_data, role_name)

                            # Fallback to text parsing if JSON contained only freeform analysis
                            if not self._findings:
                                json_text = self._extract_text_from_json(json_data)
                                if json_text:
                                    self._findings = self._extract_findings_from_text(
                                        json_text, role_name
                                    )

                        except json.JSONDecodeError:
                            # Try JSONL (one JSON object per line)
                            jsonl_objects = self._parse_jsonl(output_text)
                            if jsonl_objects:
                                agent_logs.append(
                                    f"[{datetime.now().strftime('%H:%M:%S')}] Parsed JSONL response"
                                )
                                combined_text = []
                                for obj in jsonl_objects:
                                    self._findings.extend(
                                        self._extract_findings_from_json(obj, role_name)
                                    )
                                    obj_text = self._extract_text_from_json(obj)
                                    if obj_text:
                                        combined_text.append(obj_text)

                                if not self._findings and combined_text:
                                    self._findings = self._extract_findings_from_text(
                                        "\n".join(combined_text),
                                        role_name,
                                    )
                            else:
                                agent_logs.append(
                                    f"[{datetime.now().strftime('%H:%M:%S')}] Output not valid JSON, treating as text"
                                )
                                # Extract findings from text output
                                self._findings = self._extract_findings_from_text(
                                    output_text, role_name
                                )

                    except UnicodeDecodeError as e:
                        agent_logs.append(
                            f"[{datetime.now().strftime('%H:%M:%S')}] Failed to decode output: {e}"
                        )
                        errors.append(f"Failed to decode agent output: {e}")

                else:
                    error_output = (
                        stderr.decode("utf-8", errors="replace") if stderr else "No stderr"
                    )
                    agent_logs.append(
                        f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Process failed with error: {error_output}"
                    )
                    errors.append(f"OpenCode process failed: {error_output}")

            except asyncio.TimeoutError:
                agent_logs.append(
                    f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Process timed out after {self.config.timeout_seconds}s"
                )
                errors.append(f"Agent timed out after {self.config.timeout_seconds}s")

                if self.config.verbose:
                    print(f"⏰ {role_name} analysis timed out after {self.config.timeout_seconds}s")
                process.kill()

        except Exception as e:
            agent_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Unexpected error: {e}")
            errors.append(f"Agent execution failed: {e}")

            if self.config.verbose:
                print(f"❌ {role_name} analysis failed: {e}")
            logger.exception("ACP runner failed")

        duration = (datetime.now() - start_time).total_seconds()

        # Save the agent logs as an artifact
        try:
            from superqode.workspace.artifacts import ArtifactManager

            manager = ArtifactManager(self.project_root)
            manager.initialize("qe_logs")

            log_content = "\n".join(agent_logs)
            log_artifact = manager.save_log(
                name=f"QE Agent Analysis - {role_name}", content=log_content, log_type="qe_agent"
            )
            agent_logs.append(
                f"[{datetime.now().strftime('%H:%M:%S')}] Logs saved to: {log_artifact.path}"
            )
        except Exception as e:
            logger.warning(f"Failed to save agent logs: {e}")

        return ACPRunnerResult(
            success=len(errors) == 0 and len(self._findings) > 0,
            findings=self._findings,
            agent_output=collected_output,
            tool_calls=tool_calls,
            duration_seconds=duration,
            errors=errors,
        )

    def _extract_findings_from_json(self, json_data: dict, role_name: str) -> List[ACPFinding]:
        """Extract findings from OpenCode JSON output."""
        findings = []

        # OpenCode JSON structure varies, but typically has analysis results
        # Look for findings, issues, or analysis sections
        if isinstance(json_data, dict):
            # Try different possible structures
            potential_findings = (
                json_data.get("findings", [])
                or json_data.get("issues", [])
                or json_data.get("results", [])
                or json_data.get("analysis", {}).get("findings", [])
                or [json_data]
                if json_data.get("title") or json_data.get("description")
                else []
            )

            for item in potential_findings:
                if isinstance(item, dict) and (item.get("title") or item.get("description")):
                    self._finding_counter += 1
                    finding = ACPFinding(
                        id=f"{role_name}-{self._finding_counter:03d}",
                        severity=item.get("severity", "medium").lower(),
                        title=item.get("title", item.get("description", "")[:50]),
                        description=item.get("description", item.get("title", "")),
                        file_path=item.get("file_path") or item.get("file") or item.get("location"),
                        line_number=item.get("line_number") or item.get("line"),
                        evidence=item.get("evidence"),
                        suggested_fix=item.get("suggested_fix") or item.get("fix"),
                        confidence=item.get("confidence", 0.8),
                        category=role_name,
                    )
                    findings.append(finding)

        return findings

    def _extract_text_from_json(self, json_data: Any) -> str:
        """Extract freeform analysis text from a JSON payload."""
        if isinstance(json_data, str):
            return json_data

        if not isinstance(json_data, dict):
            return ""

        # Common fields that may contain analysis text
        for key in ("analysis", "text", "content", "message", "output", "response"):
            value = json_data.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, dict):
                for nested_key in ("text", "content", "message", "analysis"):
                    nested_val = value.get(nested_key)
                    if isinstance(nested_val, str):
                        return nested_val

        return ""

    def _parse_jsonl(self, output_text: str) -> List[dict]:
        """Parse JSONL output into a list of JSON objects."""
        objects = []
        for line in output_text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                objects.append(obj)
        return objects

    def _extract_findings_from_text(self, text_output: str, role_name: str) -> List[ACPFinding]:
        """Extract findings from OpenCode text output."""
        findings = []

        # Use the existing text extraction logic
        self._collected_output = text_output
        self._extract_findings_from_output(role_name)

        return self._findings

    def _check_agent_available(self) -> bool:
        """Check if the agent command is available."""
        cmd = self.config.agent_command.split()[0]
        return shutil.which(cmd) is not None

    def _build_agent_command(self, role_name: str = "qe") -> str:
        """Build the agent command with model configuration."""
        cmd_parts = self.config.agent_command.split()

        # If model is specified and using opencode, add model flag
        if self.config.model and "opencode" in self.config.agent_command:
            cmd_parts.extend(["-m", f"opencode/{self.config.model}"])

        return " ".join(cmd_parts)

    def _handle_event(self, event: StreamEvent):
        """Handle streaming events from the agent."""
        if event.event_type == StreamEventType.MESSAGE_CHUNK:
            msg: StreamMessage = event.data
            self._collected_output += msg.text

            # Forward to custom handler if provided
            if self.config.on_event:
                self.config.on_event(event)

        elif event.event_type == StreamEventType.THOUGHT_CHUNK:
            self._collected_thoughts += event.data.text

        elif event.event_type == StreamEventType.TOOL_CALL:
            tool_call: StreamToolCall = event.data
            self._tool_calls.append(
                {
                    "id": tool_call.tool_id,
                    "title": tool_call.title,
                    "kind": tool_call.kind.value,
                    "status": tool_call.status.value,
                }
            )

            if self.config.on_event:
                self.config.on_event(event)

        elif event.event_type == StreamEventType.ERROR:
            logger.error(f"Agent error: {event.data}")

            if self.config.on_event:
                self.config.on_event(event)

    def _extract_findings_from_output(self, role_name: str):
        """
        Extract structured findings from agent output.

        Looks for patterns like:
        - **CRITICAL**: ...
        - **HIGH**: ...
        - **MEDIUM**: ...
        - **LOW**: ...
        - Issue: ...
        - Bug: ...
        - Vulnerability: ...
        """
        output = self._collected_output

        # Pattern for severity-prefixed findings
        severity_pattern = (
            r"\*\*(CRITICAL|HIGH|MEDIUM|LOW|INFO)\*\*:\s*(.+?)(?=\n\*\*[A-Z]+\*\*:|\n\n|\Z)"
        )
        severity_colon_pattern = (
            r"(?m)^(CRITICAL|HIGH|MEDIUM|LOW|INFO)\s*:\s*(.+?)"
            r"(?=\n(?:CRITICAL|HIGH|MEDIUM|LOW|INFO)\s*:|\n\n|\Z)"
        )

        for match in re.finditer(severity_pattern, output, re.IGNORECASE | re.DOTALL):
            severity = match.group(1).lower()
            content = match.group(2).strip()

            # Extract title (first line) and description (rest)
            lines = content.split("\n", 1)
            title = lines[0].strip()
            description = lines[1].strip() if len(lines) > 1 else title

            # Try to extract file path and line number
            file_path, line_number = self._extract_location(content)

            self._finding_counter += 1
            finding = ACPFinding(
                id=f"{role_name}-{self._finding_counter:03d}",
                severity=severity,
                title=title,
                description=description,
                file_path=file_path,
                line_number=line_number,
                confidence=0.8,
                category=role_name,
            )
            self._findings.append(finding)

        for match in re.finditer(severity_colon_pattern, output, re.IGNORECASE | re.DOTALL):
            severity = match.group(1).lower()
            content = match.group(2).strip()

            lines = content.split("\n", 1)
            title = lines[0].strip()
            description = lines[1].strip() if len(lines) > 1 else title

            file_path, line_number = self._extract_location(content)

            self._finding_counter += 1
            finding = ACPFinding(
                id=f"{role_name}-{self._finding_counter:03d}",
                severity=severity,
                title=title,
                description=description,
                file_path=file_path,
                line_number=line_number,
                confidence=0.8,
                category=role_name,
            )
            self._findings.append(finding)

        # Pattern for issue/bug/vulnerability prefixed findings
        issue_pattern = r"(?:Issue|Bug|Vulnerability|Problem|Warning):\s*(.+?)(?=\n(?:Issue|Bug|Vulnerability|Problem|Warning):|\n\n|\Z)"

        for match in re.finditer(issue_pattern, output, re.IGNORECASE | re.DOTALL):
            content = match.group(1).strip()

            # Skip if we already captured this as a severity-prefixed finding
            if any(f.description in content or content in f.description for f in self._findings):
                continue

            lines = content.split("\n", 1)
            title = lines[0].strip()
            description = lines[1].strip() if len(lines) > 1 else title

            file_path, line_number = self._extract_location(content)

            # Infer severity from keywords
            severity = self._infer_severity(content)

            self._finding_counter += 1
            finding = ACPFinding(
                id=f"{role_name}-{self._finding_counter:03d}",
                severity=severity,
                title=title,
                description=description,
                file_path=file_path,
                line_number=line_number,
                confidence=0.7,
                category=role_name,
            )
            self._findings.append(finding)

        # Also look for JSON-formatted findings
        self._extract_json_findings(output, role_name)

    def _extract_location(self, content: str) -> tuple:
        """Extract file path and line number from content."""
        # Pattern: path/to/file.py:123 or path/to/file.py line 123
        file_pattern = r"([a-zA-Z0-9_\-./\\]+\.[a-zA-Z]+)(?::(\d+)| line (\d+))?"

        match = re.search(file_pattern, content)
        if match:
            file_path = match.group(1)
            line_number = match.group(2) or match.group(3)
            return file_path, int(line_number) if line_number else None

        return None, None

    def _infer_severity(self, content: str) -> str:
        """Infer severity from content keywords."""
        content_lower = content.lower()

        critical_keywords = ["critical", "security", "vulnerability", "injection", "xss", "exploit"]
        high_keywords = ["high", "severe", "dangerous", "unsafe", "memory leak"]
        medium_keywords = ["medium", "warning", "potential", "may cause"]
        low_keywords = ["low", "minor", "style", "suggestion", "consider"]

        for kw in critical_keywords:
            if kw in content_lower:
                return "critical"

        for kw in high_keywords:
            if kw in content_lower:
                return "high"

        for kw in medium_keywords:
            if kw in content_lower:
                return "medium"

        for kw in low_keywords:
            if kw in content_lower:
                return "low"

        return "medium"  # Default

    def _extract_json_findings(self, output: str, role_name: str):
        """Extract JSON-formatted findings from output."""
        # Look for JSON blocks
        json_pattern = r"```json\s*([\s\S]*?)\s*```"

        for match in re.finditer(json_pattern, output):
            try:
                data = json.loads(match.group(1))

                # Handle array of findings
                if isinstance(data, list):
                    for item in data:
                        self._add_json_finding(item, role_name)

                # Handle single finding object
                elif isinstance(data, dict):
                    if "findings" in data:
                        for item in data["findings"]:
                            self._add_json_finding(item, role_name)
                    else:
                        self._add_json_finding(data, role_name)

            except json.JSONDecodeError:
                continue

    def _add_json_finding(self, data: Dict[str, Any], role_name: str):
        """Add a finding from JSON data."""
        if not isinstance(data, dict):
            return

        # Skip if missing required fields
        if not data.get("title") and not data.get("description"):
            return

        self._finding_counter += 1
        finding = ACPFinding(
            id=f"{role_name}-{self._finding_counter:03d}",
            severity=data.get("severity", "medium").lower(),
            title=data.get("title", data.get("description", "")[:50]),
            description=data.get("description", data.get("title", "")),
            file_path=data.get("file_path") or data.get("file") or data.get("location"),
            line_number=data.get("line_number") or data.get("line"),
            evidence=data.get("evidence"),
            suggested_fix=data.get("suggested_fix") or data.get("fix"),
            confidence=data.get("confidence", 0.8),
            category=role_name,
        )
        self._findings.append(finding)


# =============================================================================
# QE Prompts for Different Roles
# =============================================================================

QE_PROMPTS = {
    "api_tester": """You are a Senior API Quality Engineer. Analyze this codebase for API issues.

Focus on:
1. API endpoint security (authentication, authorization, input validation)
2. API contract violations
3. Error handling in API routes
4. Rate limiting and throttling
5. Data validation and sanitization

For each issue found, report in this format:
**SEVERITY**: Title
Description of the issue
File: path/to/file.py:line_number
Evidence: code snippet or explanation

Start your analysis now. Be thorough but concise.""",
    "security_tester": """You are a Senior Security Engineer. Analyze this codebase for security vulnerabilities.

Focus on:
1. OWASP Top 10 vulnerabilities
2. SQL/NoSQL injection points
3. XSS vulnerabilities
4. Authentication/authorization flaws
5. Sensitive data exposure
6. Hardcoded secrets or credentials

For each vulnerability found, report in this format:
**SEVERITY**: Title (e.g., **CRITICAL**: SQL Injection in user search)
Description and impact
File: path/to/file.py:line_number
Evidence: vulnerable code snippet

Start your security analysis now.""",
    "unit_tester": """You are a Senior Test Engineer. Analyze this codebase for test coverage gaps.

Focus on:
1. Functions/methods lacking unit tests
2. Edge cases not covered by existing tests
3. Error handling paths not tested
4. Complex logic without test coverage
5. Public APIs without tests

For each gap found, report in this format:
**MEDIUM**: Missing tests for function_name
Description of what should be tested
File: path/to/file.py:line_number
Suggested test cases: brief description

Analyze the test coverage now.""",
    "e2e_tester": """You are a Senior E2E Test Engineer. Analyze this codebase for workflow testing gaps.

Focus on:
1. Critical user workflows not tested
2. Integration points between components
3. User journey edge cases
4. State management issues
5. Cross-component data flow

For each issue found, report in this format:
**SEVERITY**: Title
Description of the workflow issue
Files involved: list files
Suggested E2E test scenario

Analyze user workflows now.""",
    "performance_tester": """You are a Senior Performance Engineer. Analyze this codebase for performance issues.

Focus on:
1. N+1 query patterns
2. Memory leak patterns
3. Inefficient algorithms (O(n²) or worse)
4. Missing caching opportunities
5. Blocking I/O operations
6. Large data processing without pagination

For each issue found, report in this format:
**SEVERITY**: Title (e.g., **HIGH**: N+1 query in user listing)
Description and performance impact
File: path/to/file.py:line_number
Evidence: problematic code
Suggested optimization

Analyze performance now.""",
    "fullstack": """You are a Senior QE Tech Lead with 15+ years of experience. Conduct a comprehensive code review.

Review all aspects:
1. Functional correctness - does the code do what it should?
2. Error handling - are errors handled properly?
3. Security - any security concerns?
4. Performance - any obvious bottlenecks?
5. Code quality - maintainability, readability
6. Test coverage - are there adequate tests?

For each issue found, report with severity:
**CRITICAL**: Blocks release, must fix
**HIGH**: Should fix before release
**MEDIUM**: Should fix soon
**LOW**: Nice to have

Format:
**SEVERITY**: Title
Description with business impact
File: path/to/file.py:line_number
Evidence and suggested fix

Be thorough but focus on real, practical issues that affect users and business.
Start your comprehensive review now.""",
}


def get_qe_prompt(role_name: str, allow_suggestions: bool = False) -> str:
    """Get the QE prompt for a role.

    Args:
        role_name: Name of the QE role
        allow_suggestions: If True, enhance prompt to request fixes

    Returns:
        The role-specific prompt, enhanced for suggestions if enabled
    """
    # Handle qe. prefix
    if role_name.startswith("qe."):
        role_name = role_name[3:]

    base_prompt = QE_PROMPTS.get(role_name, QE_PROMPTS["fullstack"])

    if allow_suggestions:
        from superqode.enterprise import require_enterprise

        if require_enterprise("Fix suggestions and verification"):
            return _enhance_prompt_for_suggestions(base_prompt, role_name)

    return base_prompt


def _enhance_prompt_for_suggestions(base_prompt: str, role_name: str) -> str:
    """Enhance a QE prompt to request suggested fixes.

    When allow_suggestions is enabled, the agent should:
    1. Find issues as usual
    2. Generate a fix for each issue
    3. Apply the fix in sandbox
    4. Verify the fix works
    5. Report the outcome with evidence
    """
    suggestion_addendum = """

## SUGGESTION MODE ENABLED

For each issue you find, you MUST also:

1. **Generate a Fix**: Create a concrete code fix for the issue
2. **Apply the Fix**: Modify the relevant file(s) to implement the fix
3. **Verify the Fix**: Run any available tests to confirm the fix works
4. **Report Outcome**: Document what you did and whether it worked

For each finding with a fix, report in this enhanced format:

**SEVERITY**: Title
Description of the issue
File: path/to/file.py:line_number
Evidence: original problematic code

**SUGGESTED FIX**:
```diff
- old code
+ new code
```

**VERIFICATION**:
- Applied fix: Yes/No
- Tests run: list tests
- Tests passed: X/Y
- Fix verified: Yes/No

**OUTCOME**:
Brief description of what changed and confirmation the fix works.

IMPORTANT:
- Apply each fix to the actual files (you have permission in this sandbox)
- Run tests after each fix to verify
- If a fix doesn't work, try up to 3 alternative approaches
- Always report both the issue AND the fix with verification results
- The sandbox will be reverted after QE - your fixes are demonstrations only

Start your analysis with fix generation now."""

    return base_prompt + suggestion_addendum


# Prompts specifically for suggestion verification
VERIFICATION_PROMPTS = {
    "verify_fix": """You previously suggested a fix for the following issue:

Issue: {issue_title}
File: {file_path}:{line_number}
Fix applied: {fix_description}

Now verify that the fix works:

1. Run the relevant tests for this file/module
2. Check if the original issue is resolved
3. Check for any regressions (new failures)

Report your verification results:

**VERIFICATION RESULT**:
- Original issue resolved: Yes/No
- Tests run: [list of tests]
- Tests passed: X/Y
- New regressions: Yes/No (if yes, describe)
- Verification status: PASSED/FAILED/INCONCLUSIVE

If the fix caused problems, explain what went wrong.""",
    "revert_and_retry": """The previous fix attempt failed verification.

Original issue: {issue_title}
Failed fix: {failed_fix}
Failure reason: {failure_reason}

Please:
1. Revert the previous fix
2. Analyze why it failed
3. Generate an alternative fix
4. Apply and verify the new fix

Report the new attempt in the standard format.""",
}


def get_verification_prompt(
    prompt_type: str,
    issue_title: str = "",
    file_path: str = "",
    line_number: int = 0,
    fix_description: str = "",
    failed_fix: str = "",
    failure_reason: str = "",
) -> str:
    """Get a verification prompt with filled-in details."""
    template = VERIFICATION_PROMPTS.get(prompt_type, "")
    return template.format(
        issue_title=issue_title,
        file_path=file_path,
        line_number=line_number,
        fix_description=fix_description,
        failed_fix=failed_fix,
        failure_reason=failure_reason,
    )
