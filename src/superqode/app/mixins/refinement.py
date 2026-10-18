"""Launch the native refinement UI from the harness command and Hub."""

from __future__ import annotations

import shlex
from pathlib import Path


class RefinementMixin:
    def _refinement_cmd(self, args, log, *, spec=None):
        from superqode.harness.catalog import resolve_harness
        from superqode.widgets.refinement_inspector import RefinementScreen

        pure = getattr(self, "_pure_mode", None)
        session = getattr(pure, "session", None)
        selected = spec or getattr(pure, "_harness_spec", None)
        if selected is None or selected.runtime.backend != "codegem":
            selected = resolve_harness("codegem").spec
        provider = str(getattr(session, "provider", "") or "ollama")
        model = str(getattr(session, "model", "") or "")
        source = Path(getattr(session, "working_directory", None) or Path.cwd())
        task, output = args.strip(), None
        try:
            words = shlex.split(args)
            if words and words[0] in {"cancel", "apply"}:
                self._run_cli_group("harness", "refine " + args, log, "Harness2 refinement")
                return
            if words and words[0] in {"inspect", "resume"}:
                if len(words) != 2:
                    raise ValueError("Use :harness refine inspect <output-directory>")
                output, task = Path(words[1]).expanduser().resolve(), ""
                if not (output / "manifest.json").is_file():
                    raise ValueError("No saved refinement manifest exists at that path")
            screen = RefinementScreen(
                source=source,
                spec=selected,
                provider=provider,
                model=model,
                task=task,
                output=output,
            )
            self.push_screen(screen)
            if output:
                screen.call_after_refresh(screen.inspect_saved)
        except (ValueError, OSError) as exc:
            log.add_error(str(exc))
