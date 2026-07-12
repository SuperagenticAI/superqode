"""Recipe/skill file lookup and enablement."""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from superqode.providers.model_specs import (
    split_provider_model_ref,
)
from superqode.app.recipes import LocalRecipe


class HelperRecipesSkillsMixin:
    """Recipe/skill file lookup and enablement."""

    def _find_skill_file(self, skills_root: Path, name: str) -> Path | None:
        """Find a local skill file by directory, file stem, or frontmatter name."""
        candidates = [
            skills_root / name / "SKILL.md",
            skills_root / name,
            skills_root / f"{name}.md",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        if not skills_root.exists():
            return None
        for path in sorted(skills_root.rglob("*.md")):
            if path.stem.lower() == name.lower() or path.parent.name.lower() == name.lower():
                return path
            try:
                head = path.read_text(encoding="utf-8", errors="ignore")[:1000].lower()
            except Exception:
                continue
            if f"name: {name.lower()}" in head:
                return path
        return None
    def _set_skill_enabled(self, skills_root: Path, name: str, *, enabled: bool) -> bool:
        """Toggle a skill's frontmatter enabled flag."""
        path = self._find_skill_file(skills_root, name)
        if path is None:
            return False
        try:
            text = path.read_text(encoding="utf-8")
            value = "true" if enabled else "false"
            if text.startswith("---"):
                end = text.find("\n---", 3)
                if end != -1:
                    front = text[:end]
                    body = text[end:]
                    lines = front.splitlines()
                    replaced = False
                    for idx, line in enumerate(lines):
                        if line.strip().startswith("enabled:"):
                            lines[idx] = f"enabled: {value}"
                            replaced = True
                            break
                    if not replaced:
                        lines.append(f"enabled: {value}")
                    path.write_text("\n".join(lines) + body, encoding="utf-8")
                    return True
            path.write_text(f"---\nenabled: {value}\n---\n\n{text}", encoding="utf-8")
            return True
        except Exception:
            return False
    def _find_recipe(self, name: str) -> LocalRecipe | None:
        recipes = self._load_local_recipes()
        recipe = recipes.get(name)
        if recipe is not None:
            return recipe
        lowered = name.lower()
        return next((item for item in recipes.values() if item.name.lower() == lowered), None)
    @staticmethod
    def _string_tuple(value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            return (value,)
        if isinstance(value, (list, tuple)):
            return tuple(str(item) for item in value if str(item).strip())
        return ()
    @staticmethod
    def _load_recipe_file(path: Path) -> LocalRecipe | None:
        from superqode.app_main import SuperQodeApp
        try:
            raw = path.read_text(encoding="utf-8")
            if path.suffix.lower() == ".json":
                data = json.loads(raw)
            else:
                import yaml

                data = yaml.safe_load(raw) or {}
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        recipe_data = data.get("recipe") if isinstance(data.get("recipe"), dict) else data
        name = str(recipe_data.get("name") or path.stem).strip()
        if not name:
            return None
        model = str(recipe_data.get("model") or "").strip()
        provider = str(recipe_data.get("provider") or "").strip()
        if not provider and model:
            parsed_model = split_provider_model_ref(model)
            if parsed_model.provider:
                provider, model = parsed_model.provider, parsed_model.model
        variables = recipe_data.get("variables") or ()
        if isinstance(variables, dict):
            variables = tuple(str(key) for key in variables)
        return LocalRecipe(
            name=name,
            description=str(recipe_data.get("description") or "").strip(),
            path=path,
            prompt=str(recipe_data.get("prompt") or "").strip(),
            prompt_file=str(
                recipe_data.get("prompt_file") or recipe_data.get("promptFile") or ""
            ).strip(),
            provider=provider,
            model=model,
            mode=str(recipe_data.get("mode") or "").strip(),
            role=str(recipe_data.get("role") or "").strip(),
            skills=SuperQodeApp._string_tuple(recipe_data.get("skills")),
            attachments=SuperQodeApp._string_tuple(
                recipe_data.get("attachments") or recipe_data.get("attach")
            ),
            mcp_resources=SuperQodeApp._string_tuple(
                recipe_data.get("mcp_resources") or recipe_data.get("mcpResources")
            ),
            harness=str(
                recipe_data.get("harness") or recipe_data.get("harness_spec") or ""
            ).strip(),
            variables=SuperQodeApp._string_tuple(variables),
            raw=dict(recipe_data),
        )
