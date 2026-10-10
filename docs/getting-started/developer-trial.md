---
title: Developer Trial
description: A practical first-session exercise and feedback guide for trying SuperQode on your own project.
---

# Developer Trial

Use a small repository you understand for your first session. Start with one
agent or model, complete one task, review its changes, then resume the session.
A custom harness is optional.

## Install and connect

```bash
uv tool install superqode
superqode --version
cd /path/to/your/project
superqode
```

See [Installation](installation.md) if you need to install uv or choose another
installation method. Use a terminal at least 80 columns by 24 rows for the full
interface.

In the TUI, enter `:connect`. Choose the agent you already use or a local model.
Direct commands include:

```text
:connect codex
:connect claude
:connect acp opencode
:connect local
```

Complete the selected route's installation and sign-in steps. Keep approval
mode on **Ask** for the exercise. The status bar shows your active connection;
use `:status` to inspect it and `:connect retry` after a failed setup attempt.
Provider API keys and vendor subscriptions are separate connection routes.

## Complete the exercise

1. **Understand the repository.** Send: `Summarize this repository, identify its test command, and propose one small improvement. Do not change files yet.`
2. **Add context.** Type `@` to select a file. Paste a multiline instruction with `Ctrl+J` between lines; `Enter` sends it. Large pasted blocks can be inspected with `:blocks`.
3. **Make a focused change.** Ask the agent to implement the agreed improvement and run the relevant test. Read the exact command or file operation before approving. Reject a request once and give a useful alternative.
4. **Interrupt and recover.** During a run, press `Ctrl+C`. Check that work stops and your unsent draft remains. Send a follow-up instruction. Two idle `Ctrl+C` presses within two seconds exit; `:exit` also exits.
5. **Review the result.** Open `:diff task` and `:delivery`. Check the changed files, the reported test results, and whether the change matches your request. Copy a response with `:copy response`.
6. **Continue later.** Exit, reopen SuperQode in the same repository, and use `:sessions` or `:resume latest`. Check the project, harness, model, and continuity description before continuing.
7. **Try another harness.** Open `:hub` or `:harness switch`. Check whether the target is ready or needs setup. Switching can replay context; a replay is different from resuming the original agent's native session.
8. **Personalize the terminal.** Open `:theme`, search the offline gallery, and preview a palette. Escape should cancel; Enter should install if needed, apply, and save. Try `:theme import` with a local JSON file and check that your draft remains. Reopen SuperQode to confirm the saved selection. See [Themes](../advanced/themes.md) for the full workflow.

Use `Ctrl+K` for the command palette and `F1` for help. `Escape` closes a panel
and returns to the previous view. `:home` returns home; `:disconnect` detaches
the model and harness.

## Report what happened

Open `:feedback` or **Export feedback** in the command palette.
Describe the problem and review the displayed JSON. You can exclude recent
errors or harness/model names. The bundle records the version, platform,
terminal size, theme and appearance preferences, selected route, and a bounded
error tail. It excludes conversation history, source files, session IDs and
configuration dumps. Known credentials, common token formats, private keys,
authenticated URL parameters and local home/project paths are redacted.

Select **I reviewed this diagnostic bundle**, choose an export path, and click
**Export JSON**. Editing the notes or options clears the review acknowledgment.
The exported JSON matches the reviewed snapshot, uses private file permissions,
and retains any existing destination file. It is saved locally; nothing is
uploaded automatically. Review the file for private information before sharing
it with the SuperQode maintainers.

Include the following in feedback or an issue:

- SuperQode version, operating system, terminal application, and terminal size.
- Agent or model, connection route, and whether you used a subscription, API key, or local server.
- The steps you took, what you expected, and what happened instead.
- Whether the draft, conversation, or connection was lost, and how you recovered.
- A screenshot or a short transcript with credentials, private source, and personal information removed.
- Approximate time to your first successful task and the hardest step to discover.
- Theme name, light/dark terminal appearance, and any hard-to-read text or clipped controls.

Also note which agent you normally use and one interaction SuperQode should
make more familiar. Feedback on setup, trust, recovery, and change review is as
useful as feedback on model answers.
