"""
Init command - Initialize SuperQE configuration for a project.

Supports guided mode with:
- Framework detection (React, Django, FastAPI, etc.)
- Team size configuration
- Provider setup with API key detection
- Validation with quick scan
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

console = Console()


@dataclass
class FrameworkInfo:
    """Detected framework information."""

    name: str
    category: str  # "frontend", "backend", "fullstack", "cli"
    language: str
    recommended_roles: List[str]
    test_patterns: List[str]


# Framework detection rules
FRAMEWORK_DETECTORS = {
    # Frontend frameworks
    "next.js": {
        "files": ["next.config.js", "next.config.mjs", "next.config.ts"],
        "package_json_deps": ["next"],
        "info": FrameworkInfo(
            name="Next.js",
            category="fullstack",
            language="typescript",
            recommended_roles=["e2e_tester", "api_tester", "unit_tester"],
            test_patterns=["**/*.test.tsx", "**/*.spec.tsx", "**/__tests__/**"],
        ),
    },
    "react": {
        "files": [],
        "package_json_deps": ["react", "react-dom"],
        "info": FrameworkInfo(
            name="React",
            category="frontend",
            language="typescript",
            recommended_roles=["e2e_tester", "unit_tester"],
            test_patterns=["**/*.test.tsx", "**/*.test.jsx", "**/*.spec.tsx"],
        ),
    },
    "vue": {
        "files": ["vue.config.js", "vite.config.ts"],
        "package_json_deps": ["vue"],
        "info": FrameworkInfo(
            name="Vue.js",
            category="frontend",
            language="typescript",
            recommended_roles=["e2e_tester", "unit_tester"],
            test_patterns=["**/*.spec.ts", "**/*.test.ts"],
        ),
    },
    # Backend frameworks
    "django": {
        "files": ["manage.py"],
        "pyproject_deps": ["django"],
        "requirements_deps": ["django", "Django"],
        "info": FrameworkInfo(
            name="Django",
            category="backend",
            language="python",
            recommended_roles=[
                "api_tester",
                "security_tester",
                "unit_tester",
                "performance_tester",
            ],
            test_patterns=["**/test_*.py", "**/tests.py", "**/tests/*.py"],
        ),
    },
    "fastapi": {
        "files": [],
        "pyproject_deps": ["fastapi"],
        "requirements_deps": ["fastapi"],
        "info": FrameworkInfo(
            name="FastAPI",
            category="backend",
            language="python",
            recommended_roles=[
                "api_tester",
                "security_tester",
                "unit_tester",
                "performance_tester",
            ],
            test_patterns=["**/test_*.py", "**/tests/*.py"],
        ),
    },
    "flask": {
        "files": [],
        "pyproject_deps": ["flask"],
        "requirements_deps": ["flask", "Flask"],
        "info": FrameworkInfo(
            name="Flask",
            category="backend",
            language="python",
            recommended_roles=["api_tester", "security_tester", "unit_tester"],
            test_patterns=["**/test_*.py"],
        ),
    },
    "express": {
        "files": [],
        "package_json_deps": ["express"],
        "info": FrameworkInfo(
            name="Express.js",
            category="backend",
            language="typescript",
            recommended_roles=["api_tester", "security_tester", "unit_tester"],
            test_patterns=["**/*.test.js", "**/*.spec.js"],
        ),
    },
    # Go frameworks
    "go-chi": {
        "files": [],
        "go_mod_deps": ["github.com/go-chi/chi"],
        "info": FrameworkInfo(
            name="Go Chi",
            category="backend",
            language="go",
            recommended_roles=["api_tester", "performance_tester", "unit_tester"],
            test_patterns=["**/*_test.go"],
        ),
    },
    "go-gin": {
        "files": [],
        "go_mod_deps": ["github.com/gin-gonic/gin"],
        "info": FrameworkInfo(
            name="Go Gin",
            category="backend",
            language="go",
            recommended_roles=["api_tester", "performance_tester", "unit_tester"],
            test_patterns=["**/*_test.go"],
        ),
    },
    # Rust
    "rust-actix": {
        "files": [],
        "cargo_deps": ["actix-web"],
        "info": FrameworkInfo(
            name="Actix Web",
            category="backend",
            language="rust",
            recommended_roles=["api_tester", "performance_tester", "unit_tester"],
            test_patterns=["**/tests/*.rs"],
        ),
    },
}


# Provider detection (check environment variables)
PROVIDER_ENV_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "xai": "XAI_API_KEY",
    "zhipuai": "ZHIPUAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "groq": "GROQ_API_KEY",
    "together": "TOGETHER_API_KEY",
}

DEFAULT_CONFIG = """# SuperQode Configuration (used by SuperQE)
# https://super-agentic.ai/superqode

superqode:
  version: "1.0"
  team_name: "{team_name}"

qe:
  # Output settings
  output:
    directory: ".superqode"
    reports_format: "markdown"
    keep_history: true

  # Execution modes
  modes:
    quick_scan:
      timeout: 60
      depth: shallow
      generate_tests: false
      destructive: false

    deep_qe:
      timeout: 1800
      depth: full
      generate_tests: true
      destructive: true

  # Execution roles (deterministic - run existing tests only)
  execution_roles:
    smoke:
      test_pattern: "**/test_smoke*.py"
      fail_fast: true

    sanity:
      test_pattern: "**/test_sanity*.py"
      fail_fast: false

    regression:
      test_pattern: "**/test_*.py"
      detect_flakes: true

  # Noise controls
  noise:
    min_confidence: 0.7
    deduplicate: true
    suppress_known_risks: false
    min_severity: "low"  # low, medium, high, critical

  # Harness validation
  harness:
    enabled: true
    timeout_seconds: 30
    python_tools: ["ruff", "mypy"]
    javascript_tools: ["eslint"]
    go_tools: ["go vet"]
    rust_tools: ["cargo check"]
    shell_tools: ["shellcheck"]
    custom_steps:
      - name: "project-harness"
        command: "python scripts/harness_check.py"
        timeout_seconds: 120
        enabled: false

  # SuperOpt optimization hook (command-based, optional)
  qe:
    optimize:
      enabled: false
      command: ""

# Provider configuration (for BYOK mode)
providers:
  anthropic:
    api_key_env: "ANTHROPIC_API_KEY"
  openai:
    api_key_env: "OPENAI_API_KEY"
  google:
    api_key_env: "GOOGLE_API_KEY"
"""


def _detect_frameworks(project_root: Path) -> List[FrameworkInfo]:
    """Detect frameworks used in the project."""
    detected = []

    # Read package.json if exists
    package_json_deps = set()
    package_json_path = project_root / "package.json"
    if package_json_path.exists():
        try:
            import json

            pkg = json.loads(package_json_path.read_text())
            package_json_deps.update(pkg.get("dependencies", {}).keys())
            package_json_deps.update(pkg.get("devDependencies", {}).keys())
        except Exception:
            pass

    # Read pyproject.toml if exists
    pyproject_deps = set()
    pyproject_path = project_root / "pyproject.toml"
    if pyproject_path.exists():
        try:
            content = pyproject_path.read_text()
            # Simple parsing - look for dependencies section
            for line in content.split("\n"):
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    dep = line.split("=")[0].strip().strip('"').lower()
                    pyproject_deps.add(dep)
        except Exception:
            pass

    # Read requirements.txt if exists
    requirements_deps = set()
    for req_file in ["requirements.txt", "requirements-dev.txt", "requirements/base.txt"]:
        req_path = project_root / req_file
        if req_path.exists():
            try:
                for line in req_path.read_text().split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#"):
                        dep = line.split("==")[0].split(">=")[0].split("[")[0].strip()
                        requirements_deps.add(dep.lower())
            except Exception:
                pass

    # Read go.mod if exists
    go_mod_deps = set()
    go_mod_path = project_root / "go.mod"
    if go_mod_path.exists():
        try:
            for line in go_mod_path.read_text().split("\n"):
                if line.strip() and not line.startswith("module") and not line.startswith("go "):
                    dep = line.strip().split()[0]
                    go_mod_deps.add(dep)
        except Exception:
            pass

    # Read Cargo.toml if exists
    cargo_deps = set()
    cargo_path = project_root / "Cargo.toml"
    if cargo_path.exists():
        try:
            content = cargo_path.read_text()
            in_deps = False
            for line in content.split("\n"):
                if "[dependencies]" in line:
                    in_deps = True
                elif line.startswith("[") and in_deps:
                    in_deps = False
                elif in_deps and "=" in line:
                    dep = line.split("=")[0].strip()
                    cargo_deps.add(dep)
        except Exception:
            pass

    # Check each framework
    for framework_id, detector in FRAMEWORK_DETECTORS.items():
        found = False

        # Check for specific files
        for file_pattern in detector.get("files", []):
            if (project_root / file_pattern).exists():
                found = True
                break

        # Check package.json dependencies
        if not found:
            for dep in detector.get("package_json_deps", []):
                if dep in package_json_deps:
                    found = True
                    break

        # Check pyproject.toml dependencies
        if not found:
            for dep in detector.get("pyproject_deps", []):
                if dep.lower() in pyproject_deps:
                    found = True
                    break

        # Check requirements.txt dependencies
        if not found:
            for dep in detector.get("requirements_deps", []):
                if dep.lower() in requirements_deps:
                    found = True
                    break

        # Check go.mod dependencies
        if not found:
            for dep in detector.get("go_mod_deps", []):
                if any(dep in d for d in go_mod_deps):
                    found = True
                    break

        # Check Cargo.toml dependencies
        if not found:
            for dep in detector.get("cargo_deps", []):
                if dep in cargo_deps:
                    found = True
                    break

        if found:
            detected.append(detector["info"])

    return detected


def _detect_providers() -> List[Tuple[str, str]]:
    """Detect configured providers from environment variables."""
    configured = []
    for provider, env_var in PROVIDER_ENV_VARS.items():
        if os.environ.get(env_var):
            configured.append((provider, env_var))
    return configured


def _create_guided_config(
    team_name: str,
    team_size: str,
    frameworks: List[FrameworkInfo],
    provider: Optional[str],
) -> str:
    """Create configuration based on guided setup choices."""
    # Collect recommended roles from frameworks
    roles = set()
    test_patterns = []
    for fw in frameworks:
        roles.update(fw.recommended_roles)
        test_patterns.extend(fw.test_patterns)

    # Add default roles if none detected
    if not roles:
        roles = {"unit_tester", "api_tester", "security_tester"}

    # Adjust roles based on team size
    if team_size == "solo":
        # Minimal set for solo developers
        roles = {"unit_tester", "security_tester"}
    elif team_size == "small":
        # Keep detected roles, add security
        roles.add("security_tester")
    # "full" keeps all detected roles

    # Build roles section
    roles_yaml = ""
    role_configs = {
        "unit_tester": 'description: "Unit testing with coverage analysis"',
        "api_tester": 'description: "API endpoint testing and validation"',
        "security_tester": 'description: "Security vulnerability scanning"',
        "e2e_tester": 'description: "End-to-end user journey testing"',
        "performance_tester": 'description: "Performance and load testing"',
    }

    for role in sorted(roles):
        if role in role_configs:
            roles_yaml += f"""
    {role}:
      {role_configs[role]}
      enabled: true"""

    # Build test patterns
    patterns_yaml = ""
    if test_patterns:
        unique_patterns = list(set(test_patterns))[:5]  # Limit to 5
        patterns_yaml = "\n      ".join(f'- "{p}"' for p in unique_patterns)

    # Provider config
    provider_section = ""
    if provider:
        provider_section = f"""
# Default provider
default:
  provider: {provider}
"""

    # Framework info comment
    framework_comment = ""
    if frameworks:
        fw_names = ", ".join(fw.name for fw in frameworks)
        framework_comment = f"# Detected frameworks: {fw_names}\n"

    return f'''{framework_comment}# SuperQode Configuration (used by SuperQE)
# Generated by guided setup

superqode:
  version: "2.0"
  team_name: "{team_name}"
{provider_section}
team:
  qe:
    description: "Quality Engineering"
    roles:{roles_yaml}

qe:
  output:
    directory: ".superqode"
    reports_format: "markdown"

  modes:
    quick_scan:
      timeout: 60
      depth: shallow

    deep_qe:
      timeout: 1800
      depth: full
      generate_tests: true

  noise:
    min_confidence: 0.7
    deduplicate: true
    min_severity: "low"

  harness:
    enabled: true
    timeout_seconds: 30
'''


@click.command("init")
@click.argument("path", type=click.Path(), default=".")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing configuration")
@click.option("--minimal", "-m", is_flag=True, help="Create minimal configuration")
@click.option("--guided", "-g", is_flag=True, help="Run guided setup wizard")
def init(path: str, force: bool, minimal: bool, guided: bool):
    """Initialize SuperQE configuration for a project.

    Creates a superqode.yaml configuration file and .superqode directory.

    Examples:

        superqe init              # Initialize current directory

        superqe init ./myproject  # Initialize specific directory

        superqe init --minimal    # Create minimal config

        superqe init --guided     # Run guided setup wizard
    """
    project_root = Path(path).resolve()

    console.print()
    console.print(Panel("[bold]SuperQE Initialization[/bold]", border_style="cyan"))
    console.print()

    # Check if project exists
    if not project_root.exists():
        console.print(f"[red]Error:[/red] Path does not exist: {project_root}")
        return 1

    config_file = project_root / "superqode.yaml"
    superqode_dir = project_root / ".superqode"

    # Check for existing config
    if config_file.exists() and not force:
        console.print(f"[yellow]Configuration already exists:[/yellow] {config_file}")
        if not Confirm.ask("Overwrite existing configuration?"):
            console.print("[dim]Initialization cancelled.[/dim]")
            return 0

    # Guided setup mode
    if guided:
        return _run_guided_setup(project_root, config_file, superqode_dir)

    # Standard setup
    # Detect project info
    team_name = _detect_team_name(project_root)

    # Ask for team name
    team_name = Prompt.ask("Team name", default=team_name)

    # Create configuration
    if minimal:
        config_content = _create_minimal_config(team_name)
    else:
        config_content = DEFAULT_CONFIG.format(team_name=team_name)

    # Write config file
    config_file.write_text(config_content)
    console.print(f"[green]✓[/green] Created {config_file}")
    console.print(
        "[dim]⚡ Power QE roles: unit, integration, api, ui, accessibility, security, usability[/dim]"
    )
    console.print(
        "[dim]💡 Tip: Update each role's job_description in superqode.yaml for best results[/dim]"
    )

    # Create .superqode directory structure
    _create_superqode_directory(superqode_dir)

    # Detect test patterns
    _detect_and_suggest_patterns(project_root)

    console.print()
    console.print("[green]SuperQE initialized successfully![/green]")
    console.print()
    console.print("[dim]Next steps:[/dim]")
    console.print("  1. Review superqode.yaml and customize settings")
    console.print("  2. Run [cyan]superqe run . --mode quick[/cyan] for a quick scan")
    console.print("  3. Run [cyan]superqe run . --mode deep[/cyan] for full analysis")
    console.print()

    return 0


def _run_guided_setup(project_root: Path, config_file: Path, superqode_dir: Path) -> int:
    """Run the guided setup wizard."""
    console.print("[bold cyan]Step 1/4: Project Detection[/bold cyan]")
    console.print()

    # Detect frameworks
    frameworks = _detect_frameworks(project_root)
    if frameworks:
        console.print("[green]Detected frameworks:[/green]")
        table = Table(show_header=False, box=None)
        table.add_column("Framework", style="cyan")
        table.add_column("Category")
        table.add_column("Language")
        for fw in frameworks:
            table.add_row(fw.name, fw.category, fw.language)
        console.print(table)
    else:
        console.print("[dim]No specific framework detected[/dim]")

    # Detect test files
    _detect_and_suggest_patterns(project_root)
    console.print()

    # Step 2: Team size
    console.print("[bold cyan]Step 2/4: Team Size[/bold cyan]")
    console.print()
    console.print("Select your team size to optimize QE role configuration:")
    console.print("  [cyan]1[/cyan]. Solo developer (minimal roles, fast feedback)")
    console.print("  [cyan]2[/cyan]. Small team (2-10 people, balanced coverage)")
    console.print("  [cyan]3[/cyan]. Full team (all roles enabled)")
    console.print()

    team_size_choice = Prompt.ask("Team size", choices=["1", "2", "3"], default="2")
    team_size_map = {"1": "solo", "2": "small", "3": "full"}
    team_size = team_size_map[team_size_choice]
    console.print()

    # Step 3: Provider configuration
    console.print("[bold cyan]Step 3/4: Provider Configuration[/bold cyan]")
    console.print()

    configured_providers = _detect_providers()
    selected_provider = None

    if configured_providers:
        console.print("[green]Detected API keys:[/green]")
        for provider, env_var in configured_providers:
            console.print(f"  [cyan]{provider}[/cyan] ({env_var})")
        console.print()

        if len(configured_providers) == 1:
            selected_provider = configured_providers[0][0]
            console.print(f"[dim]Using {selected_provider} as default provider[/dim]")
        else:
            provider_names = [p[0] for p in configured_providers]
            selected_provider = Prompt.ask(
                "Select default provider", choices=provider_names, default=provider_names[0]
            )
    else:
        console.print("[yellow]No API keys detected in environment.[/yellow]")
        console.print("[dim]You can configure providers later in superqode.yaml[/dim]")
        console.print()
        console.print("Free tier options:")
        console.print("  - ZhipuAI (ZHIPUAI_API_KEY)")
        console.print("  - Groq (GROQ_API_KEY)")
        console.print()

    console.print()

    # Step 4: Team name
    console.print("[bold cyan]Step 4/4: Team Name[/bold cyan]")
    console.print()
    team_name = _detect_team_name(project_root)
    team_name = Prompt.ask("Team name", default=team_name)
    console.print()

    # Generate configuration
    config_content = _create_guided_config(
        team_name=team_name,
        team_size=team_size,
        frameworks=frameworks,
        provider=selected_provider,
    )

    # Write config file
    config_file.write_text(config_content)
    console.print(f"[green]✓[/green] Created {config_file}")
    console.print(
        "[dim]⚡ Power QE roles: unit, integration, api, ui, accessibility, security, usability[/dim]"
    )
    console.print(
        "[dim]💡 Tip: Update each role's job_description in superqode.yaml for best results[/dim]"
    )

    # Create directory structure
    _create_superqode_directory(superqode_dir)

    # Success message
    console.print()
    console.print(
        Panel("[bold green]SuperQE initialized successfully![/bold green]", border_style="green")
    )
    console.print()

    # Show what was configured
    if frameworks:
        fw_names = ", ".join(fw.name for fw in frameworks)
        console.print(f"[dim]Frameworks:[/dim] {fw_names}")
    console.print(f"[dim]Team size:[/dim] {team_size}")
    if selected_provider:
        console.print(f"[dim]Provider:[/dim] {selected_provider}")
    console.print()

    # Offer to run quick scan
    if Confirm.ask("Run a quick scan to validate setup?", default=True):
        console.print()
        console.print("[cyan]Running quick scan...[/cyan]")
        console.print()
        try:
            result = subprocess.run(
                ["superqe", "run", str(project_root), "--mode", "quick"],
                cwd=str(project_root),
            )
            if result.returncode == 0:
                console.print()
                console.print("[green]Setup validated successfully![/green]")
            else:
                console.print()
                console.print(
                    "[yellow]Quick scan completed with findings. Check the report above.[/yellow]"
                )
        except Exception as e:
            console.print(f"[dim]Could not run quick scan: {e}[/dim]")
    else:
        console.print()
        console.print("[dim]Next steps:[/dim]")
        console.print("  1. Run [cyan]superqe run . --mode quick[/cyan] for a quick scan")
        console.print("  2. Run [cyan]superqe dashboard[/cyan] to view results")
        console.print()

    return 0


def _create_superqode_directory(superqode_dir: Path) -> None:
    """Create the .superqode directory structure."""
    superqode_dir.mkdir(exist_ok=True)
    (superqode_dir / "qe-artifacts").mkdir(exist_ok=True)
    (superqode_dir / "qe-artifacts" / "patches").mkdir(exist_ok=True)
    (superqode_dir / "qe-artifacts" / "generated-tests").mkdir(exist_ok=True)
    (superqode_dir / "qe-artifacts" / "qr").mkdir(exist_ok=True)
    (superqode_dir / "history").mkdir(exist_ok=True)
    console.print(f"[green]✓[/green] Created {superqode_dir}/")

    # Create .gitignore in .superqode
    gitignore_file = superqode_dir / ".gitignore"
    gitignore_content = """# SuperQode / SuperQE temporary files
temp/
*.log
workspace-state.json

# Keep artifacts
!qe-artifacts/
"""
    gitignore_file.write_text(gitignore_content)


def _detect_team_name(project_root: Path) -> str:
    """Detect team name from project directory or git config."""
    # Try to get from git config
    try:
        import subprocess

        result = subprocess.run(
            ["git", "config", "user.name"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return f"{result.stdout.strip()}'s Team"
    except Exception:
        pass

    # Fall back to directory name
    return f"{project_root.name} Team"


def _create_minimal_config(team_name: str) -> str:
    """Create a minimal configuration."""
    return f'''# SuperQode Configuration (Minimal, used by SuperQE)
superqode:
  version: "1.0"
  team_name: "{team_name}"

qe:
  modes:
    quick_scan:
      timeout: 60
    deep_qe:
      timeout: 1800

  noise:
    min_confidence: 0.7
    deduplicate: true
'''


def _detect_and_suggest_patterns(project_root: Path) -> None:
    """Detect existing test patterns and suggest configuration."""
    patterns_found = []

    # Python tests
    pytest_files = list(project_root.glob("**/test_*.py"))
    if pytest_files:
        patterns_found.append(f"  - Python (pytest): {len(pytest_files)} test files")

    # JavaScript tests
    jest_files = list(project_root.glob("**/*.test.js")) + list(project_root.glob("**/*.spec.js"))
    if jest_files:
        patterns_found.append(f"  - JavaScript (jest): {len(jest_files)} test files")

    # TypeScript tests
    ts_test_files = list(project_root.glob("**/*.test.ts")) + list(
        project_root.glob("**/*.spec.ts")
    )
    if ts_test_files:
        patterns_found.append(f"  - TypeScript: {len(ts_test_files)} test files")

    # Go tests
    go_test_files = list(project_root.glob("**/*_test.go"))
    if go_test_files:
        patterns_found.append(f"  - Go: {len(go_test_files)} test files")

    if patterns_found:
        console.print()
        console.print("[dim]Detected test files:[/dim]")
        for p in patterns_found:
            console.print(p)
