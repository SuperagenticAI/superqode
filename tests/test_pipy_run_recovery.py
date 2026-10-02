"""Abrupt process recovery of the real coding loop and its model/tool IDs."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = r"""
import asyncio, json, os, sys, time
from pathlib import Path
from dataclasses import replace
from superqode.execution_recovery import RecoveryScope, recovery_scope
from superqode.workorders import WorkOrder, WorkOrderTask, WorkOrderStore, WorkOrderBudget
from superqode.pipy.coding_session import CodingSessionOptions, PiPyCodingSession
from superqode.pipy.ai import FakeStream, text_response, tool_response
from superqode.pipy.messages import ToolCall
from superqode.pipy.stream import Model
from superqode.harness.pipy_adapter import PiPyHarnessProtocolAdapter
from superqode.harness.pipy_governance import guard_pipy_tools
from superqode.harness.protocol import HarnessSessionRef, HarnessMessage
from superqode.harness.pipy_recovery import PiPyRecoveryRequired
import superqode.harness.pipy_adapter as adapter_module
root=Path(sys.argv[1]); stage=sys.argv[2]
control=root/'.superqode'; control.mkdir(exist_ok=True)
store=WorkOrderStore(control/'work.sqlite3')
if stage!='resume':
 store.create(WorkOrder(work_order_id='work', goal='write', repository=str(root), harness='pipy',
  budget=WorkOrderBudget(**json.loads(os.getenv('RECOVERY_TEST_BUDGET','{}'))),
  tasks=(WorkOrderTask(task_id='task',title='write',goal='write',max_attempts=8),)))
 store.queue('work')
else:
 import superqode.workorders.store as store_module
 original_time=time.time
 store_module.time.time=lambda:original_time()+1000
 store.recover_stale('work')
 store_module.time.time=original_time
claimed=store.claim_next_task(worker_id=stage,reference='work',lease_seconds=1 if stage!='resume' else 300)
if claimed is None:
 print(json.dumps({'status':'blocked','error':'WorkOrder requires reconciliation'}));sys.exit(0)
_,task=claimed
scope=RecoveryScope(store,'work','task',stage,task.attempts)
session_path=control/'session.jsonl'
adapter_module._record_session_path=lambda *a:None
adapter_module._indexed_session_path=lambda *a:str(session_path) if session_path.exists() else ''
model=Model(id='fixture',provider='fixture')
responses=[tool_response(ToolCall(id='original-write',name='write',arguments={'path':'result.txt','content':'correct'})), text_response('finished')]
async def stream(model,context,options):
 file=control/'requests.json'; n=json.loads(file.read_text()) if file.exists() else 0
 file.write_text(json.dumps(n+1))
 if stage=='model-in-flight':os._exit(72)
 return FakeStream([responses[n]])(model,context,options)
def transform(tools):
 result=[]
 for tool in tools:
  if tool.name=='write':
   original=tool.execute_fn
   async def write(call,args,signal=None,on_update=None,original=original):
    with (control/'writes.log').open('a') as f:f.write(call+'\n')
    result=await original(call,args,signal,on_update)
    if stage=='write-in-flight':os._exit(72)
    return result
   tool=replace(tool,execute_fn=write)
  result.append(tool)
 return guard_pipy_tools(result)
async def factory(request,cwd,path):
 opts=CodingSessionOptions(cwd=root,model=model,stream_fn=stream,session_root=control/'sessions',tool_transform=transform)
 if path:return await PiPyCodingSession.resume(opts,session_path=path)
 session=await PiPyCodingSession.create(opts)
 # Use the actual repository-assigned path and persist it for the next host.
 (control/'path').write_text(str(session.session_path))
 return session
adapter_module._indexed_session_path=lambda *a:(control/'path').read_text() if (control/'path').exists() else ''
original_finish=store.finish_invocation
seen=[]
def finish(*args,**kwargs):
 original_finish(*args,**kwargs)
 ident=kwargs['invocation_id'];seen.append(ident)
 if (stage=='after-model' and ident=='pipy.model/1') or (stage=='after-write' and ident.endswith('pipy.tool.write/original-write')) or (stage=='after-final' and ident=='pipy.model/2'):
  os._exit(72)
store.finish_invocation=finish
async def main():
 adapter=PiPyHarnessProtocolAdapter(session_factory=factory)
 ref=HarnessSessionRef(session_id='coding',harness_id='pipy',metadata={'working_directory':str(root),'runtime_config':{'recovery':{'enabled':True},'mcp_config':False}})
 try:
  from superqode.governance import governance_scope, load_governance
  policy=json.loads(os.getenv('RECOVERY_TEST_POLICY','{}'))
  with recovery_scope(scope), governance_scope(load_governance(root,session_policy=policy)):
   ref=await adapter.resume(ref)
   events=[event async for event in adapter.send(ref,HarnessMessage('user','write the result'))]
  print(json.dumps({'status':'complete','events':len(events)}))
 except PiPyRecoveryRequired as error:
  print(json.dumps({'status':'blocked','error':str(error)}))
 finally:await adapter.close(ref)
asyncio.run(main())
"""


def process(root, stage, *, environment=None):
    return subprocess.run(
        [sys.executable, "-c", SCRIPT, str(root), stage],
        capture_output=True,
        text=True,
        timeout=20,
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
            **(environment or {}),
        },
    )


@pytest.mark.parametrize("stage", ["after-model", "after-write", "after-final"])
def test_coding_process_restores_original_calls_without_duplicate_model_or_write(tmp_path, stage):
    first = process(tmp_path, stage)
    assert first.returncode == 72, first.stderr
    resumed = process(tmp_path, "resume")
    assert resumed.returncode == 0, resumed.stderr
    assert json.loads(resumed.stdout)["status"] == "complete", resumed.stdout
    assert (tmp_path / "result.txt").read_text() == "correct"
    assert json.loads((tmp_path / ".superqode/requests.json").read_text()) == 2
    assert (tmp_path / ".superqode/writes.log").read_text().splitlines() == ["original-write"]


@pytest.mark.parametrize("stage", ["model-in-flight", "write-in-flight"])
def test_unknown_model_or_write_outcome_blocks_without_repeat(tmp_path, stage):
    first = process(tmp_path, stage)
    assert first.returncode == 72, first.stderr
    resumed = process(tmp_path, "resume")
    assert resumed.returncode == 0, resumed.stderr
    assert json.loads(resumed.stdout)["status"] == "blocked"
    assert json.loads((tmp_path / ".superqode/requests.json").read_text()) == 1
    writes = tmp_path / ".superqode/writes.log"
    assert not writes.exists() or len(writes.read_text().splitlines()) == 1


def test_workspace_drift_blocks_coding_restore(tmp_path):
    first = process(tmp_path, "after-write")
    assert first.returncode == 72, first.stderr
    (tmp_path / "result.txt").write_text("external change")
    resumed = process(tmp_path, "resume")
    assert json.loads(resumed.stdout)["status"] == "blocked"
    assert (tmp_path / "result.txt").read_text() == "external change"


def test_current_request_policy_rechecked_before_cached_model_reuse(tmp_path):
    first = process(tmp_path, "after-model")
    assert first.returncode == 72, first.stderr
    policy = {
        "rules": [
            {
                "id": "deny-current-model",
                "phase": "request",
                "action": "deny",
                "message": "changed policy",
            }
        ]
    }
    resumed = process(tmp_path, "resume", environment={"RECOVERY_TEST_POLICY": json.dumps(policy)})
    assert resumed.returncode == 0, resumed.stderr
    assert json.loads(resumed.stdout)["status"] == "blocked"
    assert not (tmp_path / "result.txt").exists()
    assert json.loads((tmp_path / ".superqode/requests.json").read_text()) == 1


def test_unknown_provider_spend_cannot_bypass_declared_cap(tmp_path):
    result = process(
        tmp_path,
        "after-model",
        environment={"RECOVERY_TEST_BUDGET": json.dumps({"max_cost_usd": 1})},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "blocked"
    assert not (tmp_path / ".superqode/requests.json").exists()


def runner_script():
    code = SCRIPT.replace("harness='pipy',", "harness=str(control/'recover.yaml'),")
    code = code.replace(
        "store=WorkOrderStore(control/'work.sqlite3')",
        "(control/'recover.yaml').write_text('name: pipy-recover\\nruntime:\\n  backend: pipy\\n  config:\\n    mcp_config: false\\n    recovery:\\n      enabled: true\\n')\nstore=WorkOrderStore(control/'work.sqlite3')",
    )
    start = code.index("async def main():")
    code = (
        code[:start]
        + r"""
original_init=PiPyHarnessProtocolAdapter.__init__
def init(self,**kwargs):original_init(self,session_factory=factory)
PiPyHarnessProtocolAdapter.__init__=init
async def main():
 from superqode.workorders.runner import execute_claimed_task
 execution=await execute_claimed_task(store,order=store.get('work'),task=task,worker_id=stage,
   lease_seconds=300,provider='openai',model='gpt-4o-mini',isolation='none')
 print(json.dumps({'status':execution.status,'error':execution.error,
  'artifacts':[a.kind for a in store.get('work').artifacts],
  'usage':store.usage_summary('work').to_dict()}))
asyncio.run(main())
"""
    )
    return code


def test_actual_workorder_runner_recovers_coding_and_publishes_patch(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".superqode/\n")
    subprocess.run(["git", "add", ".gitignore"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
    )
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    first = subprocess.run(
        [sys.executable, "-c", runner_script(), str(tmp_path), "after-write"],
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )
    assert first.returncode == 72, first.stderr
    resumed = subprocess.run(
        [sys.executable, "-c", runner_script(), str(tmp_path), "resume"],
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )
    assert resumed.returncode == 0, resumed.stderr
    result = json.loads(resumed.stdout)
    assert result["status"] == "succeeded", result
    assert "patch" in result["artifacts"] and "agent_result" in result["artifacts"]
    assert json.loads((tmp_path / ".superqode/requests.json").read_text()) == 2
    assert (tmp_path / ".superqode/writes.log").read_text().splitlines() == ["original-write"]
