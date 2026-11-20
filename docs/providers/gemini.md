# Gemini models

Google models in SuperQode are a **model** route, not a Gemini CLI coding-agent
route. SuperQode does not offer Gemini CLI on `:connect`.

## Google's coding agent

Use [Antigravity](antigravity.md) for Google's signed-in agent:

```text
:connect antigravity
```

## Gemini inside SuperQode's harness

Use BYOK when SuperQode should own tools, approvals, and the loop, on a Gemini
model:

```text
:connect byok google <model>
```

Set `GEMINI_API_KEY` or `GOOGLE_API_KEY`. See [Bring Your Own Key](byok.md).
For the Google-focused native harness, its six tools, and a headless first run,
see [CodeGem](../advanced/codegem.md).

Without a thinking level, Google's per-model default applies, which is `high`
for Gemini 4 Neon and can feel slow for everyday edits. A harness file can set
one for Gemini 3 and Gemini 4 models on this route:

```yaml
model_policy:
  reasoning: medium
```

SuperQode sends the nearest level the model documents: `off` becomes the
lowest level and `max` the highest, such as `xhigh` on Neon.

## Related documentation

- [Google Antigravity](antigravity.md)
- [ACP Coding Agents](acp.md)
- [Connection methods](../concepts/modes.md)
