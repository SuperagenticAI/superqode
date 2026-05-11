"""
A2A Workflow Engine - Multi-agent orchestration with A2A.

Supports sequential, parallel, hierarchical, and fan-out/fan-in patterns.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from enum import Enum

from .client import A2AClient, A2AClientPool, A2AClientError
from .types import Task, AgentCard


class WorkflowPattern(str, Enum):
    """Workflow orchestration patterns."""
    SEQUENTIAL = "sequential"      # A → B → C
    PARALLEL = "parallel"          # A || B || C
    SUPERVISOR = "supervisor"      # Supervisor delegates to sub-agents
    FAN_OUT_FAN_IN = "fan_out_fan_in"  # Dispatch, collect, aggregate


@dataclass
class WorkflowStep:
    """A single step in a workflow."""
    name: str
    agent_url: str
    prompt_template: Optional[str] = None  # Template with {previous_result}
    on_error: Optional[str] = None  # "continue", "abort", "retry"


@dataclass
class WorkflowResult:
    """Result of a workflow execution."""
    pattern: WorkflowPattern
    steps: List[Dict[str, Any]]
    final_result: Optional[str] = None
    success: bool = True
    error: Optional[str] = None
    total_time: float = 0.0


class A2AWorkflowEngine:
    """Multi-agent workflow orchestration engine.
    
    Usage:
        engine = A2AWorkflowEngine()
        
        # Sequential: A → B → C
        result = await engine.sequential([
            {"url": "http://agent-a:8000", "prompt": "Write code"},
            {"url": "http://agent-b:8000", "prompt": "Test code"},
            {"url": "http://agent-c:8000", "prompt": "Deploy"},
        ])
        
        # Parallel: A || B || C
        result = await engine.parallel([
            {"url": "http://test-agent:8000", "prompt": "Run unit tests"},
            {"url": "http://security-agent:8000", "prompt": "Security scan"},
            {"url": "http://lint-agent:8000", "prompt": "Lint code"},
        ])
    """

    def __init__(self):
        self._client_pool = A2AClientPool()

    async def add_agent(self, name: str, url: str):
        """Add an agent to the workflow pool."""
        await self._client_pool.add(name, url)

    async def remove_agent(self, name: str):
        """Remove an agent from the pool."""
        await self._client_pool.remove(name)

    async def get_agent_card(self, name: str) -> Optional[AgentCard]:
        """Get agent capabilities."""
        return await self._client_pool.get_card(name)

    async def sequential(
        self,
        steps: List[WorkflowStep],
        initial_message: str,
    ) -> WorkflowResult:
        """Execute steps sequentially (A → B → C).
        
        Args:
            steps: List of workflow steps
            initial_message: Starting message
            
        Returns:
            WorkflowResult with all step results
        """
        import time
        start_time = time.time()
        
        results = []
        current_message = initial_message
        
        for step in steps:
            try:
                client = A2AClient(step.agent_url)
                task = await client.send_message(
                    step.prompt_template.format(previous_result=current_message) 
                    if step.prompt_template 
                    else current_message
                )
                
                result_text = self._extract_result(task)
                results.append({
                    "step": step.name,
                    "status": task.status.state.value,
                    "result": result_text,
                })
                
                current_message = result_text
                await client.close()
                
            except Exception as e:
                results.append({
                    "step": step.name,
                    "status": "failed",
                    "error": str(e),
                })
                
                if step.on_error == "abort":
                    break
                elif step.on_error == "continue":
                    continue

        return WorkflowResult(
            pattern=WorkflowPattern.SEQUENTIAL,
            steps=results,
            final_result=current_message,
            success=all(r.get("status") == "completed" for r in results),
            total_time=time.time() - start_time,
        )

    async def parallel(
        self,
        steps: List[WorkflowStep],
        message: str,
    ) -> WorkflowResult:
        """Execute steps in parallel (A || B || C).
        
        Args:
            steps: List of workflow steps
            message: Same message to all agents
            
        Returns:
            WorkflowResult with all results
        """
        import time
        start_time = time.time()
        
        results = []
        
        async def run_step(step: WorkflowStep) -> Dict[str, Any]:
            try:
                client = A2AClient(step.agent_url)
                task = await client.send_message(message)
                result_text = self._extract_result(task)
                await client.close()
                return {
                    "step": step.name,
                    "status": task.status.state.value,
                    "result": result_text,
                }
            except Exception as e:
                return {
                    "step": step.name,
                    "status": "failed",
                    "error": str(e),
                }

        # Run all steps concurrently
        task_results = await asyncio.gather(*[run_step(s) for s in steps])
        results = list(task_results)

        return WorkflowResult(
            pattern=WorkflowPattern.PARALLEL,
            steps=results,
            final_result=self._aggregate_results(results),
            success=all(r.get("status") == "completed" for r in results),
            total_time=time.time() - start_time,
        )

    async def supervisor(
        self,
        supervisor_url: str,
        sub_agents: List[WorkflowStep],
        task: str,
    ) -> WorkflowResult:
        """Execute supervisor pattern - supervisor delegates to sub-agents.
        
        The supervisor analyzes the task and delegates to appropriate sub-agents,
        then aggregates results.
        
        Args:
            supervisor_url: URL of supervisor agent
            sub_agents: Available sub-agents
            task: Task for supervisor to analyze
            
        Returns:
            WorkflowResult from supervisor execution
        """
        import time
        start_time = time.time()
        
        # First, ask supervisor to decompose task
        supervisor = A2AClient(supervisor_url)
        
        # Build context about available sub-agents
        agent_context = "\n".join([
            f"- {s.name}: {s.agent_url}" for s in sub_agents
        ])
        
        decomposition_prompt = f"""Analyze this task and delegate to appropriate agents.

Available agents:
{agent_context}

Task: {task}

Return a JSON dict mapping agent names to their specific tasks."""
        
        try:
            # Get decomposition from supervisor
            decompose_task = await supervisor.send_message(decomposition_prompt)
            await supervisor.close()
            
            # Execute delegated tasks in parallel
            results = []
            for sub in sub_agents:
                results.append({
                    "step": sub.name,
                    "status": "delegated",
                    "result": f"Delegated to {sub.name}",
                })
            
            return WorkflowResult(
                pattern=WorkflowPattern.SUPERVISOR,
                steps=results,
                final_result=self._extract_result(decompose_task),
                success=decompose_task.status.state.value == "completed",
                total_time=time.time() - start_time,
            )
            
        except Exception as e:
            return WorkflowResult(
                pattern=WorkflowPattern.SUPERVISOR,
                steps=[],
                error=str(e),
                success=False,
                total_time=time.time() - start_time,
            )

    async def fan_out_fan_in(
        self,
        dispatcher_url: str,
        worker_urls: List[str],
        task: str,
    ) -> WorkflowResult:
        """Execute fan-out/fan-in pattern.
        
        Dispatch task to multiple workers, wait for all results, then aggregate.
        
        Args:
            dispatcher_url: URL of dispatcher agent
            worker_urls: URLs of worker agents
            task: Task to process
            
        Returns:
            WorkflowResult with aggregated results
        """
        import time
        start_time = time.time()
        
        results = []
        
        async def run_worker(url: str, worker_id: int) -> Dict[str, Any]:
            try:
                client = A2AClient(url)
                task_result = await client.send_message(task)
                await client.close()
                return {
                    "worker": f"worker_{worker_id}",
                    "status": task_result.status.state.value,
                    "result": self._extract_result(task_result),
                }
            except Exception as e:
                return {
                    "worker": f"worker_{worker_id}",
                    "status": "failed",
                    "error": str(e),
                }

        # Fan-out: dispatch to all workers
        worker_results = await asyncio.gather(*[
            run_worker(url, i) for i, url in enumerate(worker_urls)
        ])
        results = list(worker_results)
        
        # Fan-in: aggregate results
        aggregated = self._aggregate_results(results)
        
        return WorkflowResult(
            pattern=WorkflowPattern.FAN_OUT_FAN_IN,
            steps=results,
            final_result=aggregated,
            success=all(r.get("status") == "completed" for r in results),
            total_time=time.time() - start_time,
        )

    def _extract_result(self, task: Task) -> str:
        """Extract text result from task."""
        if not task.history:
            return ""
        
        # Get last agent message
        for msg in reversed(task.history):
            if msg.role == MessageRole.AGENT:
                if msg.parts and msg.parts[0].text:
                    return msg.parts[0].text
        
        return ""

    def _aggregate_results(self, results: List[Dict[str, Any]]) -> str:
        """Aggregate multiple results into single summary."""
        lines = []
        for r in results:
            status = r.get("status", "unknown")
            result = r.get("result", r.get("error", ""))
            lines.append(f"[{r.get('step', r.get('worker', 'unknown'))}] {status}: {result[:100]}")
        
        return "\n".join(lines)

    async def close(self):
        """Close all client connections."""
        await self._client_pool.close_all()


class A2ATool:
    """A2A client as a SuperQode tool - call external A2A agents from within SuperQode.
    
    Usage in SuperQode:
        // Call external A2A agent for security testing
        Use the a2a_call tool to invoke external agents for specialized tasks.
    """

    def __init__(self):
        self.name = "a2a_call"
        self.description = """Call an external A2A-compliant agent.

Use this to delegate tasks to specialized external agents:
- Security testing agents
- Specialized code review agents  
- External testing frameworks
- Other A2A-compliant agents

Arguments:
- agent_url: URL of the A2A agent
- message: Task to send to the agent
- timeout: Optional timeout in seconds (default: 60)"""

    async def execute(
        self,
        agent_url: str,
        message: str,
        timeout: float = 60.0,
    ) -> Dict[str, Any]:
        """Execute A2A call to external agent."""
        client = A2AClient(agent_url, timeout=timeout)
        
        try:
            # Get agent card first
            card = await client.get_agent_card()
            
            # Send message
            task = await client.send_message(message)
            
            return {
                "success": True,
                "agent_name": card.name,
                "task_id": task.task_id,
                "status": task.status.state.value,
                "result": self._extract_result(task),
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
        finally:
            await client.close()

    def _extract_result(self, task: Task) -> str:
        if not task.history:
            return ""
        for msg in reversed(task.history):
            if msg.role == MessageRole.AGENT:
                if msg.parts and msg.parts[0].text:
                    return msg.parts[0].text
        return ""