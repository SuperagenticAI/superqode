# Z.AI GLM

SuperQode supports GLM-5.2 and other GLM-5.x models through Z.AI's first-party
general API. SuperQode owns the coding harness, tools, approvals, and workspace
execution; Z.AI provides the model inference endpoint.

## Important endpoint boundary

This integration intentionally uses the general API endpoint:

```text
https://api.z.ai/api/paas/v4
```

It does **not** use the GLM Coding Plan endpoint. Z.AI restricts Coding Plan
quota to officially supported tools, and SuperQode is not currently listed.
Use a general Z.AI API key created in the Z.AI developer platform.

## Setup

```bash
export ZAI_API_KEY=your-general-api-key

# Show provider details without making a model request
superqode connect setup zai

# Test and select a model
superqode connect zai glm-5.2
```

You may override the general endpoint for an approved enterprise proxy:

```bash
export ZAI_API_BASE=https://api.z.ai/api/paas/v4
```

Do not set `ZAI_API_BASE` to `/api/coding/paas/v4` unless Z.AI has explicitly
approved SuperQode for Coding Plan use.

## TUI

From the TUI, either open the Z.AI profile or specify the provider and model:

```text
:connect zai
:connect zai/glm-5.2
```

You can also launch directly into the Z.AI profile:

```bash
superqode --connect zai
```

Z.AI's general API is a BYOK route, so it is not shown on the Subscriptions
screen. A paid GLM Coding Plan is available separately through
`:connect glm-cli`.

## GLM CLI (community ACP agent)

`glm-acp-agent` is a community-maintained ACP agent that uses GLM models as its
reasoning engine. It is not a first-party Z.ai client, and it runs its own agent
loop instead of the SuperQode harness:

```bash
npm install -g glm-acp-agent
```

```text
:connect glm-cli
```

`:connect acp glm` reaches the same agent through the generic ACP picker.

| Goal | Route |
| --- | --- |
| Use GLM models inside the SuperQode harness | `:connect zai` |
| Use the community GLM agent loop | `:connect glm-cli` |

## ZCode

[ZCode](https://zcode.z.ai/en) is Z.AI's official desktop harness for GLM-5.3.
It is discoverable in the SuperQode Harness Hub under **Coming soon**, but it is
not the same integration as either route above. ZCode currently owns its own
desktop agent loop, tools, permissions, browser automation, review flow, and
task history.

SuperQode does not claim direct ZCode support until Z.AI publishes a supported
ACP server, headless CLI, or external agent SDK. Use `:hub coming` to inspect
the tracked entry and its official documentation.

## GLM-5.2 harness

The `glm52-coding` template uses the first-party Z.AI route, GLM-family model
policy, native tools, long-horizon history, and GLM-5.2 reasoning controls:

```bash
superqode harness init my-glm-agent --template glm52-coding
superqode harness inspect --spec my-glm-agent.yaml --json
superqode --harness glm52-coding -p "Review this repository"
```

Default model routing:

1. `zai/glm-5.2`
2. `zai/glm-5.1`
3. `zai/glm-5`

## Optional live smoke test

The automated suite never spends API quota by default. To run the paid live
smoke test explicitly:

```bash
SUPERQODE_LIVE_ZAI=1 \
ZAI_API_KEY=your-general-api-key \
pytest tests/test_zai_provider.py -k live -q
```

Override the live model when necessary:

```bash
export SUPERQODE_LIVE_ZAI_MODEL=glm-5.1
```
