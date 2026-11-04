# Subscription onboarding and Chinese model support

Research date: 4 November 2026. SuperQode baseline: `23f3cba543cea209ab780ccd22d6020cb240f7fb`, Python 2.31.2 and macOS 0.3.3 build 19.

**Recommendation: make the default Mac experience a simple coding workspace that reuses an existing agent or plan. Put Qwen, GLM and DeepSeek first in discovery, with Kimi and MiniMax alongside them. Keep harness engineering available as an advanced workflow.** Most of the connection machinery already exists; accurate plan selection, account reuse and recovery need work.

This is feasible, but a subscription is specific to its service and access method. A coding-plan key, consumer chat login, metered API balance and local model are different routes even when they serve the same model family. A plan authenticated inside an external coding agent does not automatically supply SuperQode Core with model access.

## Recommended routes

| Choice users recognise | What SuperQode already has | Recommended path and remaining work |
| --- | --- | --- |
| Qwen / Alibaba | First-party Qwen Code over ACP; Alibaba API provider; local Qwen presets. | Prioritise reuse of an existing Qwen Code configuration. Add guided current plan setup and explicit platform/region selection. Fix stale authentication instructions and handle the released agent's login metadata. |
| GLM / Z.AI / Zhipu | General API providers, GLM presets and a community `glm-acp-agent` route labelled GLM Coding Plan. | Distinguish the general API from a Coding Plan. Guide supported-agent configurations where current eligibility is confirmed. Clearly label the community adapter. Investigate the official ZCode CLI/app-server as a separate integration. |
| DeepSeek | First-party DeepSeek Harness through a pinned Python SDK, API-key inference, local DeepSeek/DS4 setup. | Offer API balance and local models accurately today. Investigate upstream account login and newer ACP as a separate runtime upgrade. Do not describe an account login or recharge balance as proof of an included flat-rate subscription. |
| Kimi | First-party Kimi Code over ACP, Moonshot API provider, native Kimi presets. | Reuse the CLI account and its advertised terminal sign-in. Keep membership access separate from Moonshot API credits. Direct membership-model access for Core/PiPy is still marked as pending. |
| MiniMax | A dedicated Token Plan provider and separate credential variable exist; model-subscription picker entries are guidance-only. | Resolve that product inconsistency and validate the dedicated plan route before making it a recommended native onboarding card. Do not reuse a general API key as a plan key. |
| Codex / ChatGPT | Native Codex app-server connection, account verification and API-fallback protection. | Reuse this as the quality standard for installed-agent detection, account sign-in and explicit billing identity. |
| Google | Actual connection profiles include Gemini CLI over ACP and Antigravity sign-in. | Keep the available agent routes easy to find and correct the stale Gemini documentation that says the CLI is unavailable. Plan entitlement remains Google's decision. |
| Claude Code | Current documented Anthropic routes use API credentials; the app does not offer Pro/Max as a subscription route. | Treat subscription integration as a separate compatibility and permitted-use investigation. Do not advertise it as already supported or transplant consumer tokens into the API provider. |

Chinese model preference and account geography are independent choices. An international developer may prefer Qwen or GLM; a Chinese interface does not determine the correct endpoint. Also distinguish an open-source harness from a model with open weights. Model licensing and availability must be attached to the exact selected model, not inferred from the vendor name.

## Confirmed upstream changes

### Qwen Code: the highest-priority onboarding fix

The published npm `@qwen-code/qwen-code@0.26.7` points to Git commit `f45c34d8ccbd651f2f0f4d97c9b013c11af52f5b`. Its [authentication guide](https://github.com/QwenLM/qwen-code/blob/f45c34d8ccbd651f2f0f4d97c9b013c11af52f5b/docs/users/configuration/auth.md) confirms:

- The old Qwen OAuth free tier was discontinued on 15 April 2026 and is no longer offered in the authentication menu.
- The standalone `qwen auth` command was removed. It prints a migration notice and exits; users should launch `qwen` and run `/auth`.
- QwenCloud Token Plan is a subscription with monthly Credit quota. It has separate China and international endpoints.
- Alibaba ModelStudio Coding Plan uses its own plan key and endpoint. Its Token Plan is described separately as usage-based billing; the word "plan" alone does not mean fixed-price included usage.
- An Alibaba-hosted plan may offer several Chinese model families, subject to its current model list. It is a distinct service from a Z.AI or Kimi subscription.

The important endpoint families are:

| Service | Mainland China | International |
| --- | --- | --- |
| QwenCloud Token Plan | `https://token-plan.maas.qianwenaiapi.com/compatible-mode/v1` | `https://token-plan.maas.qwencloudapi.com/compatible-mode/v1` |
| ModelStudio Coding Plan | `https://coding.dashscope.aliyuncs.com/v1` | `https://coding-intl.dashscope.aliyuncs.com/v1` |
| ModelStudio Token Plan | `https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` | `https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1` |

These values should be maintained in a reviewed route catalog, with the service, plan type, credential reference and allowed models bound together. Prefix checks can catch mistakes; they do not verify entitlement. Avoid a universal "Qwen key" field that guesses the endpoint.

Two concrete SuperQode mismatches were reproduced offline:

1. `connection_profiles.py` and `docs/providers/qwen-code.md` still recommend `qwen auth`. The legacy `plan-qwen` guidance also points users toward Qwen OAuth.
2. Qwen's released [ACP authentication methods](https://github.com/QwenLM/qwen-code/blob/f45c34d8ccbd651f2f0f4d97c9b013c11af52f5b/packages/cli/src/acp-integration/authMethods.ts) put the terminal hint in `_meta.type` and `_meta.args`. SuperQode reads only top-level `type` and therefore projects this method as `agent`; `terminal_auth_plan` rejects it as lacking an advertised terminal method. This blocks the intended guided terminal path. The exact vendor setup command still needs verification; translating the metadata alone does not prove that the complete `/auth` wizard will run.

Reproduction with the published response shape:

```python
from superqode.desktop_service.connection_probe import public_auth_methods, terminal_auth_plan

methods = [{
    "id": "openai",
    "name": "Use OpenAI API key",
    "_meta": {"type": "terminal", "args": ["--auth-type=openai"]},
}]
print(public_auth_methods(methods))  # currently projects type="agent"
terminal_auth_plan({}, methods, "openai")  # rejects the terminal sign-in method
```

"OpenAI" here names a compatible protocol, not proof that inference uses an American model or OpenAI billing. The normal UI should identify the actual configured provider and plan, while keeping the agent's exact method details inspectable.

The current subscription environment policy is also based on older assumptions: the Qwen route strips `DASHSCOPE_API_KEY` and `QWEN_API_KEY`, but retains generic `OPENAI_API_KEY` and `OPENAI_BASE_URL`. The released Qwen guide documents that system environment values can override saved environment values. This is an incomplete guard against unintended routes, not proof that every configured Qwen plan is redirected. Bind launch settings to the selected provider and credential instead of applying an OAuth-only rule. Blindly stripping every API key would break legitimate key-authenticated plans.

### DeepSeek: account login exists upstream, but is a separate project

The reviewed [DeepSeek Harness source](https://github.com/deepseek-ai/deepseek-harness/tree/8bd073392eef6f54e921a093b95076248eb08cbb) includes distinct account and API-key model adapters. The [account adapter](https://github.com/deepseek-ai/deepseek-harness/blob/8bd073392eef6f54e921a093b95076248eb08cbb/packages/llm/llm-deepseek-account/README.md) resolves an account token through its own service, does not fall back to an API key, and handles account model listings, invalidation and quota errors.

The [account service](https://github.com/deepseek-ai/deepseek-harness/blob/8bd073392eef6f54e921a093b95076248eb08cbb/packages/credentials/deepseek-account/README.md) and controller provide browser sign-in, cancellation, sign-out, profile and balance state without exporting tokens to clients. Balance includes recharge and bonus wallets. This establishes account access machinery, not a universal paid subscription entitlement.

Published package checks also found the `0.2.1-rc.5` account modules and matching base/ACP packages in npm. Individual packages' `latest` tags can point to older versions, so resolve the exact matched dependency graph. Package availability does not establish that the full graph installs or that a live account works.

SuperQode currently pins `deepseek-harness-sdk>=0.1.0rc6,<0.2.0` and exposes API-key/local configuration. Upstream ACP is a newer route; its documented `authenticate` operation is immediate success because the ACP server itself needs no authentication. It does not provide the product account-login UI. Do not promise browser sign-in merely by adding an ACP launch command.

Next spike: install an isolated matched runtime, verify its no-key startup and public session/configuration operations, then determine the supported account-owner/login bridge. Keep the current SDK route stable until that migration passes. Use supported upstream interfaces; do not copy browser cookies or host-only tokens into SuperQode's general API configuration.

### GLM: prefer a clearly supported route

SuperQode currently gives conflicting messages: the GLM subscription profile advertises a community ACP agent, while general Z.AI and legacy plan guidance restrict Coding Plan usage to supported tools. The upstream plan-policy site was inaccessible from this environment, so this review does not certify the adapter's current plan eligibility. Technical endpoint compatibility does not settle that question.

The official [ZCode repository](https://github.com/zai-org/ZCode/tree/a9fe401eede6e6e5e01be9048679c206fe6f02d9) now contains a CLI, an app-server entry and JSON/NDJSON prompt output. Its [CLI reference](https://github.com/zai-org/ZCode/blob/a9fe401eede6e6e5e01be9048679c206fe6f02d9/apps/zcode-cli/docs/usage/02-cli-reference.md) documents permissions, cancellation and version-dependent options. SuperQode already tracks ZCode as coming soon with embedding pending verification. This is a credible official-agent integration spike, not a finished ACP adapter. Verify authentication and plan behavior, approval events, cancellation, resume and packaging before promoting it.

For the first implementation, offer a validated supported-agent setup where available, keep general Z.AI API access separately labelled, and show the community GLM adapter explicitly as community maintained. Preserve regional separation between Z.AI and Zhipu services.

### Kimi and other existing accounts

The reviewed [Kimi Code source](https://github.com/MoonshotAI/kimi-code/tree/6974ac880d405d5565a2189925f3bef6daea6892) documents reuse of a CLI login through `kimi acp`. Its [authentication method](https://github.com/MoonshotAI/kimi-code/blob/6974ac880d405d5565a2189925f3bef6daea6892/packages/acp-server/src/auth-methods.ts) advertises a top-level terminal flow, which matches SuperQode's supported shape. Keep membership/model access and general Moonshot API credits separate. A real subscribed-account smoke test remains necessary.

Codex already provides a stronger guarded account route in SuperQode. Google sign-in routes are present in the source, despite stale provider documentation. Claude subscription access is not enabled by the current product; assess its supported integration boundary independently rather than promising all existing subscriptions work identically.

## The everyday Mac experience

Start with one question: **What do you already use?** Show Qwen, GLM, DeepSeek, Kimi and MiniMax prominently, with Codex and Google and a supported Claude/API option available. Put a working detected connection at the top and preserve the user's choice thereafter. Installed, configured, connected and entitled are separate states.

The default path should be:

1. Open a folder and choose the recognised product or a detected connection.
2. Reuse its existing account/configuration, or complete one guided setup. Ask for service/plan/region only when needed. Use the vendor's sign-in wizard first; native plan-key forms need explicit credential/endpoint binding.
3. Check startup and session capabilities without sending a coding prompt. Show "Connection ready" with the actual provider and known billing route; leave unverified entitlement labelled accurately.
4. Choose **Start coding**. Offer a small first task and ask normally for any required file or command permissions. Do not auto-send a paid smoke task merely because sign-in succeeded.

The composer should show a compact identity such as **Qwen Code · ModelStudio Coding Plan**, **GLM · Z.AI API credits**, or **DeepSeek · Local**. Use vendor-reported quota when available; otherwise show that usage is managed by the provider. Never infer unlimited usage or a zero cost from absent accounting.

Keep launch commands, protocol names, raw model IDs, harness/backend selection, MCP and environment settings in connection details or Advanced. Reuse the current ACP setup sheet, Keychain integration, model discovery and permission flow. The app should resolve one recommended compatible route and expose alternatives when requested.

Use two clear product destinations: **Code** for everyday work and **Improve harness** for authoring, evaluation and optimisation. Existing subscription-agent users can code immediately; they should not have to create a HarnessSpec or choose among every runtime first.

## Preserve the Chinese model preference

- Put validated Chinese model/agent routes first in the recommended catalog and onboarding examples. Preserve manually chosen routes and provide all providers through search.
- Offer **Prefer open models** and local serving separately from provider geography. Track exact model licenses and capabilities.
- Add stable/fast/preview family routes for Qwen, GLM and DeepSeek as they are validated. The current generic family-route registry covers Kimi; Qwen/GLM also have presets, which should not be mistaken for a shared, continuously validated family channel.
- Keep fallback within the user's selected service, model preference, plan and budget. Do not silently switch to American hosted models, a new subscription or metered API billing.
- Discover entitled models through the selected agent/provider when supported. Do not use an unrelated key or universal model list to guess account access.
- For local use, suggest a model that fits the machine and explain the download before starting it. Large GLM/DeepSeek weights should never be an automatic onboarding requirement.

For subscription-agent routes, the external agent owns its inner loop. SuperQode can improve the surrounding workflow and evaluate supported observable outcomes. Model access for a custom Core/PiPy/Strands harness needs a separately supported provider route. Also verify whether a plan permits unattended evaluation/optimisation before treating interactive coding quota as a batch inference API.

## Implementation order and acceptance

### First milestone: reliable Qwen plan onboarding

Correct the removed-command/OAuth guidance, implement a reviewed current-version vendor setup handoff, preserve the configured plan and add fixtures from actual released authentication responses. Then add the simple product-first entry point and remember the selected connection.

Acceptance: existing Qwen configuration works without re-entering credentials; a fresh user can complete a supported plan setup in-app without manually exporting environment variables; service/region are explicit; unrelated API credentials cannot redirect the selected route; cancellation preserves drafts and prior vendor settings. Reopening the app resumes the connection without replaying a prompt. Both currently supported and deliberately rejected older versions have actionable messages.

### Second milestone: GLM, DeepSeek and Kimi paths

Resolve GLM plan guidance and validate a supported-agent path. Investigate official ZCode and DeepSeek account integration in isolated runtimes. Exercise Kimi's current terminal login and existing-account reuse. Expose MiniMax's validated plan status consistently. Keep unavailable account routes out of the normal happy path rather than adding more dead-end experimental cards.

Acceptance: one verified first task, permission denial, cancellation, account expiration, unavailable model, exhausted quota and restart are exercised for each recommended route. Finder launch must work without relying on a terminal shell environment. A missing runtime has an install or recovery action; a quota error has the correct provider action and no automatic billing fallback.

### Third milestone: Chinese model harness quality

Validate curated Qwen/GLM/DeepSeek model-family presets with tool use, reasoning-history handling, edit accuracy, context pressure and supported local serving. Use isolated repository trials and real outcome graders as described in the [engine review](agent-engine-review-2026-11-04.md), while keeping bulk evaluation eligibility distinct from interactive subscription access.

Acceptance: publish bounded reproducible results for the exact model, host, harness and permissions. Keep preview models separate. First-task success and setup recovery should be measured alongside coding-task success and cost.

## Verification and limits

The selected existing connection, subscription and native ACP setup tests ran with **202 passed, 1 skipped**. One parameterised case was skipped because its entry is not a catalog account route. Passing these fixture tests does not cover the released Qwen metadata mismatch; the offline reproduction above demonstrates that missing case. No production connection code was changed for this research.

Official sources were read from GitHub and npm. The direct Z.AI and DeepSeek documentation domains were blocked by this cloud environment's network policy. No paid-account sign-in, inference call, subscription quota consumption, macOS UI test, package installation or release occurred. The suggested account routes remain subject to real supported-version and account testing.
