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

## Alibaba Model Studio subscriptions

In the macOS connection picker, open **Provider API key** and choose
**Set up Alibaba Model Studio plan…**. From Qwen Code's connection page,
install the agent if needed, then choose **Configure Qwen Code authentication…**.
In the Qwen Code terminal, open `/auth`, choose **Alibaba Model Studio**, and
select the plan and region associated with your key. For Token Plan Personal,
use the key from your subscription. For Token Plan Team, use the key from your
assigned seat. Coding Plan uses its own plan key.

Exit Qwen Code, check the connection in SuperQode and choose **Use this
connection**. The check starts the agent and opens a session. Send a small
interactive coding task to verify model access and review usage in Alibaba's
console. In the TUI, configure Qwen Code in the same way before connecting
with `:connect qwen-code`.

Qwen Code owns model selection and billing for this connection. Its
subscription keys are for interactive AI coding. Coding Plan does not include
`qwen4-max`. Core and other SuperQode harnesses use the regional Model Studio
API keys below, or the native Token Plan connection.

[Alibaba's Qwen Code setup](https://www.alibabacloud.com/help/en/model-studio/qwen-code.md) ·
[Alibaba's supported uses by plan](https://www.alibabacloud.com/help/en/model-studio/more-tools)

## Regional API keys

For Core or another BYOK harness, the model-provider picker also offers
`qwen-cn` and `qwen-intl`. These are metered Model Studio APIs, separate from
Qwen Code subscriptions and token plans. SuperQode does not choose the region.
In Model Studio, pick the region, create the key there, and copy the
OpenAI-compatible base URL. A key works only with the region that issued it.
The two routes keep credentials separate. Saving a key does not send a model
request or verify entitlement.

| Route | SuperQode key variable | Endpoint |
| --- | --- | --- |
| Region you choose, `qwen-intl` | `QWEN_INTL_API_KEY` | The OpenAI-compatible URL from that console. In the shell, set `QWEN_INTL_API_BASE`. |
| China API, `qwen-cn` | `QWEN_CN_API_KEY` | `https://dashscope.aliyuncs.com/compatible-mode/v1`, or a China workspace URL in `QWEN_CN_API_BASE`. |

The macOS **Your region** screen stays off until that URL is pasted. It accepts
an official Model Studio host (`*.maas.aliyuncs.com` or a DashScope host) whose
path is `/compatible-mode/v1`, including a region Alibaba adds later. Token
Plan and Coding Plan hosts are rejected on this route. A host outside Model
Studio is rejected so the key is not sent elsewhere. Prices and free quota
stay in the Model Studio console, because Alibaba can change them.

In the shell, set `QWEN_INTL_API_BASE` to the same URL. If that variable is
unset, existing shell commands still reach
`https://dashscope-intl.aliyuncs.com/compatible-mode/v1`. Set the variable when
the console shows a different region. A workspace URL from the region you chose
receives new features. The shared host remains the default.

Start with `qwen4-max` when the workspace lists it. Keep `qwen3.8-flash` when
you want the cheaper, faster option. You can compare them with `qwen3.7-plus`,
`glm-5.3`, and `deepseek-v4.1-flash` if your workspace offers them. The Model
Studio route translates SuperQode's thinking effort for those models. On
`qwen4-max`, an unset effort stays at low so a trial turn does not use the
API's high default. GLM-5.3 always thinks, even if the selected effort is off.
A key that starts with `sk-sp-` is not this route.

In the macOS app, choose **Alibaba Model Studio**, leave **Your region**
selected, paste the key and the endpoint, then click **Load workspace models**.
This lists model IDs without saving the key or sending a prompt. Select an ID
and use **Test model** to verify inference. In a shell or the TUI, set
`QWEN_INTL_API_BASE`, then use:

```text
superqode models --provider qwen-intl --live
:models provider qwen-intl live
:connect byok qwen-intl qwen4-max
```

The macOS picker lists the model IDs the workspace returns. Context, tool and
thinking metadata are not shown yet. GLM-5.3 always uses reasoning, so selecting
Off does not disable it. Model listing and the no-tool Test model action do not
certify tool calling or coding quality. Outside that picker, `qwen4-max` uses
the published 1,000,000-token context, so a session does not compact at about 8K.

The thinking adapter also recognises `deepseek-v4-pro` and
`deepseek-v4.1-flash-1017`, alongside the supported dated DeepSeek aliases.
For these hybrid models, Off sends `enable_thinking=false`. Pricing depends
on the workspace and model; the app links to Alibaba's pricing documentation.

For a dedicated workspace in the shell, set the matching API base variable
from the table. Use the workspace's OpenAI-compatible base URL
ending in `/compatible-mode/v1`. SuperQode lists chat models from Alibaba's
workspace catalog where available and labels offline examples as unverified.
Listing a model does not guarantee inference access or a particular price.

The metered routes reject Token Plan credentials. In the macOS app, pasting a
key that starts with `sk-sp-` switches to Token Plan instead of saving it on
pay-as-you-go.

## Token Plan

Token Plan is a separate interactive connection, `alibaba-token-plan`. It uses
an `sk-sp-` key and the fixed endpoint
`https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1`.
The model list leads with `qwen4-max`. Headless runs, evaluations, and batch
jobs are refused. `qwen4-max-preview` stays on this plan through 25 November
2026 and is excluded from metered discovery.

```text
:connect byok alibaba-token-plan qwen4-max
```

Coding Plan is not this connection. It does not include `qwen4-max`. Use Qwen
Code and `/auth` for Coding Plan. See [Alibaba's API key setup](https://www.alibabacloud.com/help/en/model-studio/get-api-key),
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
| Use a metered Model Studio model inside a SuperQode harness | `:connect byok qwen-intl qwen4-max` or `:connect byok qwen-cn <model>` |
| Use an Alibaba Token Plan key for interactive coding | `:connect byok alibaba-token-plan qwen4-max` |
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
