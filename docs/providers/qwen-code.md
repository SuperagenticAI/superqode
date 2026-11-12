# Qwen Code

Qwen Code is QwenLM's first-party coding agent. SuperQode connects to its
stable ACP server, so Qwen Code keeps its own agent behavior while SuperQode
provides the terminal, session, harness-switching, and normalized event
surface.

## Install And Authenticate

```bash
npm install -g @qwen-code/qwen-code
qwen
# Inside Qwen Code, enter /auth to configure your provider or plan.
```

Verify that SuperQode can discover it:

```bash
superqode agents show qwen
superqode agents doctor qwen
```

## Regional API keys

For Core or another BYOK harness, the model-provider picker also offers
`qwen-cn` and `qwen-intl`. These are metered Model Studio APIs, separate from
Qwen Code subscriptions and token plans:

| Route | SuperQode key variable | Default endpoint | Optional endpoint override |
| --- | --- | --- | --- |
| China API, `qwen-cn` | `QWEN_CN_API_KEY` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `QWEN_CN_API_BASE` |
| International API, `qwen-intl` | `QWEN_INTL_API_KEY` | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | `QWEN_INTL_API_BASE` |

Use a key issued for the selected region. The two routes keep credentials
separate. Saving a key does not send a model request or verify entitlement.
For an international workspace, start with `qwen3.8-flash` for speed and
`qwen3.7-plus` for a balanced option. You can compare them with `glm-5.3`
and `deepseek-v4.1-flash` if your workspace offers them. The Model Studio
route translates SuperQode's thinking effort for those models. GLM-5.3
always thinks, even if the selected effort is off.

In the macOS app, choose **Provider API key → Qwen · International API**,
enter the key and your workspace endpoint if Alibaba issued one, then click
**Load workspace models**. This lists model IDs
without saving the key or sending a prompt. Select an ID and use **Test model**
to verify inference. In a shell or the TUI, use:

```text
superqode models --provider qwen-intl --live
:models provider qwen-intl live
:connect byok qwen-intl qwen3.8-flash
```

For a dedicated workspace in the shell, set the matching API base variable
from the table. Use the workspace's OpenAI-compatible base URL
ending in `/compatible-mode/v1`. SuperQode lists chat models from Alibaba's
workspace catalog where available and labels offline examples as unverified.
Listing a model does not guarantee inference access or a particular price.

The metered routes reject Token Plan credentials. For a plan you already
have, use Qwen Code's `/auth` menu. The `qwen4-max-preview` Token Plan model
is excluded from metered discovery. See [Alibaba's API key setup](https://www.alibabacloud.com/help/en/model-studio/get-api-key),
[workspace endpoints](https://www.alibabacloud.com/help/en/model-studio/base-url),
and [models and pricing](https://www.alibabacloud.com/help/en/model-studio/models).

## Connect From The TUI

Use the direct product connection:

```text
:connect qwen-code
```

Qwen Code also appears in the unified Harness Switcher:

```text
:harness
:harness switch qwen-code
:harness switch qwen-code --fork
```

Use `--fork` when you want Qwen Code to start an independent branch instead of
continuing the current harness transition history.

## Choose The Qwen Route

Qwen is available through several distinct paths:

| Goal | Route |
| --- | --- |
| Use the complete first-party Qwen Code agent | `:connect qwen-code` |
| Use an Alibaba-hosted Qwen model inside the SuperQode native harness | `:connect byok alibaba <model>` |
| Use a local Qwen model inside the SuperQode native harness | `:connect local ollama <qwen-model>` |
| Start a repository-owned Qwen coding HarnessSpec | `superqode harness init qwen-coder --template qwen-coding --output harness.yaml` |

A coding-agent connection and a model connection are not interchangeable.
Choose Qwen Code when you want its complete agent loop. Choose BYOK or local
when you want SuperQode's native harness to own tools, approvals, context, and
workflow around a Qwen model.

## Related Documentation

- [Connection Methods and Vendors](../concepts/modes.md)
- [Agent Runtimes](../runtimes.md)
- [ACP Agents](acp.md)
- [Local Providers](local.md)
- [Bring Your Own Harness](../getting-started/bring-your-own-harness.md)
