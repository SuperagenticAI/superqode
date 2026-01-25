"""
Agent Store UI - Grid-Based Agent Browser and Installer.

Provides a visual interface for browsing, installing, and launching
agents from the agent registry.

Features:
- Grid layout with agent cards
- Category filtering
- Search functionality
- Install/uninstall actions
- Launch agents directly
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Grid, Horizontal, Vertical, ScrollableContainer
from textual.screen import Screen, ModalScreen
from textual.widgets import (
    Button,
    Header,
    Footer,
    Input,
    Label,
    OptionList,
    Select,
    Static,
)
from textual.widgets.option_list import Option
from textual.reactive import reactive
from textual.message import Message
from textual import events

# Optional clipboard support - gracefully handle if not available
try:
    import pyperclip

    HAS_CLIPBOARD = True
except ImportError:
    HAS_CLIPBOARD = False


class AgentStatus(Enum):
    """Status of an agent in the store."""

    AVAILABLE = "available"
    INSTALLED = "installed"
    RUNNING = "running"
    UPDATING = "updating"
    ERROR = "error"


@dataclass
class AgentInfo:
    """Information about an agent."""

    id: str
    name: str
    description: str
    author: str
    version: str
    category: str = "general"
    status: AgentStatus = AgentStatus.AVAILABLE
    icon: str = ""
    tags: List[str] = field(default_factory=list)
    repository: str = ""
    homepage: str = ""
    downloads: int = 0
    rating: float = 0.0
    # Installation info (populated from TOML/registry)
    install_command: str = ""
    install_description: str = ""
    run_command: str = ""
    requirements: List[str] = field(default_factory=list)
    documentation_url: str = ""


@dataclass
class InstallStep:
    """A single installation step."""

    order: int
    description: str
    command: str
    is_optional: bool = False


def copy_to_clipboard(text: str) -> bool:
    """
    Copy text to clipboard.

    Returns True if successful, False otherwise.
    """
    if not HAS_CLIPBOARD:
        return False
    try:
        pyperclip.copy(text)
        return True
    except Exception:
        return False


class InstallGuidancePanel(ModalScreen):
    """
    Modal panel showing installation guidance for an agent.

    Shows installation commands, requirements, and documentation links
    with copy buttons. Does NOT auto-install - users run commands manually.
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("c", "copy_main", "Copy Command"),
        Binding("enter", "dismiss", "Close"),
    ]

    CSS = """
    InstallGuidancePanel {
        align: center middle;
    }

    #install-dialog {
        width: 80%;
        max-width: 100;
        height: auto;
        max-height: 80%;
        background: #0a0a0a;
        border: double #a855f7;
        padding: 2;
    }

    #install-header {
        height: 3;
        margin-bottom: 1;
    }

    #install-title {
        text-style: bold;
        color: #a855f7;
    }

    #install-subtitle {
        color: #71717a;
    }

    #requirements-section {
        height: auto;
        margin-bottom: 1;
        padding: 1;
        background: #18181b;
        border: round #27272a;
    }

    #requirements-title {
        text-style: bold;
        color: #f59e0b;
        margin-bottom: 1;
    }

    #commands-section {
        height: auto;
        margin-bottom: 1;
    }

    .command-box {
        height: auto;
        margin-bottom: 1;
        padding: 1;
        background: #1a1a1a;
        border: round #3f3f46;
    }

    .command-label {
        color: #22c55e;
        margin-bottom: 0;
    }

    .command-text {
        color: #e4e4e7;
        background: #0d0d0d;
        padding: 0 1;
        margin: 0;
    }

    .copy-hint {
        color: #52525b;
        text-align: right;
    }

    #docs-section {
        height: auto;
        margin-bottom: 1;
    }

    #docs-link {
        color: #3b82f6;
    }

    #action-buttons {
        height: 3;
        margin-top: 1;
    }

    #action-buttons Button {
        margin-right: 1;
    }

    .copy-btn {
        background: #3b82f6;
    }

    .close-btn {
        background: #3f3f46;
    }
    """

    def __init__(self, agent: AgentInfo, **kwargs):
        super().__init__(**kwargs)
        self.agent = agent
        self._copied = False

    def compose(self) -> ComposeResult:
        """Compose the install guidance panel."""
        with Container(id="install-dialog"):
            # Header
            with Container(id="install-header"):
                yield Static(f" Install {self.agent.name}", id="install-title")
                yield Static(
                    "Run these commands in your terminal to install the agent",
                    id="install-subtitle",
                )

            # Requirements section
            if self.agent.requirements:
                with Container(id="requirements-section"):
                    yield Static(" Requirements", id="requirements-title")
                    reqs_text = Text()
                    for req in self.agent.requirements:
                        reqs_text.append(f"  • {req}\n", style="#a1a1aa")
                    yield Static(reqs_text)

            # Commands section
            with Container(id="commands-section"):
                # Main install command
                if self.agent.install_command:
                    with Container(classes="command-box"):
                        yield Static(
                            f" {self.agent.install_description or 'Install Command'}",
                            classes="command-label",
                        )
                        yield Static(
                            Text(f"$ {self.agent.install_command}", style="bold"),
                            classes="command-text",
                            id="main-command",
                        )
                        yield Static(
                            "[Press C to copy]" if HAS_CLIPBOARD else "",
                            classes="copy-hint",
                        )

                # Run command info
                if self.agent.run_command:
                    with Container(classes="command-box"):
                        yield Static(" Run Command (after install)", classes="command-label")
                        yield Static(
                            Text(f"$ {self.agent.run_command}", style="bold"),
                            classes="command-text",
                            id="run-command",
                        )

            # Documentation section
            if self.agent.documentation_url or self.agent.homepage or self.agent.repository:
                with Container(id="docs-section"):
                    doc_url = (
                        self.agent.documentation_url or self.agent.homepage or self.agent.repository
                    )
                    yield Static(
                        Text.assemble(
                            (" Documentation: ", "#6b7280"),
                            (doc_url, "underline #3b82f6"),
                        ),
                        id="docs-link",
                    )

            # Action buttons
            with Horizontal(id="action-buttons"):
                if HAS_CLIPBOARD:
                    yield Button(
                        " Copy Install Command",
                        id="btn-copy",
                        classes="copy-btn",
                        variant="primary",
                    )
                yield Button("Close", id="btn-close", classes="close-btn")

            # Status message
            yield Static("", id="status-message")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-copy":
            self.action_copy_main()
        elif event.button.id == "btn-close":
            self.dismiss()

    def action_copy_main(self) -> None:
        """Copy the main install command to clipboard."""
        if self.agent.install_command and copy_to_clipboard(self.agent.install_command):
            self._copied = True
            try:
                status = self.query_one("#status-message", Static)
                status.update(Text(" Copied to clipboard!", style="bold #22c55e"))
            except Exception:
                pass
        elif not HAS_CLIPBOARD:
            try:
                status = self.query_one("#status-message", Static)
                status.update(
                    Text(
                        " Copy manually: Select the command above",
                        style="#f59e0b",
                    )
                )
            except Exception:
                pass

    def action_dismiss(self) -> None:
        """Close the panel."""
        self.dismiss()


# Theme colors matching SuperQode style
THEME = {
    "purple": "#a855f7",
    "pink": "#ec4899",
    "success": "#22c55e",
    "error": "#ef4444",
    "warning": "#f59e0b",
    "info": "#3b82f6",
    "text": "#e4e4e7",
    "muted": "#71717a",
    "dim": "#52525b",
    "bg": "#0a0a0a",
    "card_bg": "#18181b",
    "border": "#3f3f46",
}

STATUS_STYLES = {
    AgentStatus.AVAILABLE: {"color": THEME["muted"], "icon": "", "label": "Available"},
    AgentStatus.INSTALLED: {"color": THEME["success"], "icon": "", "label": "Installed"},
    AgentStatus.RUNNING: {"color": THEME["purple"], "icon": "", "label": "Running"},
    AgentStatus.UPDATING: {"color": THEME["warning"], "icon": "", "label": "Updating"},
    AgentStatus.ERROR: {"color": THEME["error"], "icon": "", "label": "Error"},
}

CATEGORY_ICONS = {
    "general": "",
    "code": "",
    "docs": "",
    "test": "",
    "devops": "",
    "data": "",
    "web": "",
    "ai": "",
}


class AgentCard(Static):
    """Display card for a single agent."""

    DEFAULT_CSS = """
    AgentCard {
        width: 100%;
        height: auto;
        min-height: 8;
        background: #18181b;
        border: round #3f3f46;
        padding: 1;
        margin: 0 0 1 0;
    }

    AgentCard:hover {
        border: round #a855f7;
    }

    AgentCard:focus {
        border: round #ec4899;
    }

    AgentCard.selected {
        border: round #a855f7;
        background: #1f1f23;
    }

    AgentCard .agent-name {
        text-style: bold;
        color: #e4e4e7;
    }

    AgentCard .agent-author {
        color: #71717a;
    }

    AgentCard .agent-desc {
        color: #a1a1aa;
        margin-top: 1;
    }

    AgentCard .agent-meta {
        color: #52525b;
        margin-top: 1;
    }
    """

    can_focus = True
    selected: reactive[bool] = reactive(False)

    def __init__(
        self,
        agent: AgentInfo,
        on_select: Optional[Callable[[AgentInfo], None]] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.agent = agent
        self._on_select = on_select

    def render(self) -> Text:
        """Render the agent card."""
        t = Text()

        # Status indicator and name
        status_style = STATUS_STYLES.get(self.agent.status, STATUS_STYLES[AgentStatus.AVAILABLE])
        t.append(f"{status_style['icon']} ", style=status_style["color"])
        t.append(f"{self.agent.name}", style=f"bold {THEME['text']}")
        t.append(f" v{self.agent.version}\n", style=THEME["muted"])

        # Author
        t.append(f"by {self.agent.author}\n", style=THEME["muted"])

        # Description (truncated)
        desc = self.agent.description
        if len(desc) > 100:
            desc = desc[:97] + "..."
        t.append(f"{desc}\n", style=THEME["dim"])

        # Category and tags
        category_icon = CATEGORY_ICONS.get(self.agent.category, "")
        t.append(f"\n{category_icon} {self.agent.category}", style=THEME["muted"])

        if self.agent.tags:
            tags = " ".join(f"#{tag}" for tag in self.agent.tags[:3])
            t.append(f"  {tags}", style=THEME["dim"])

        return t

    def watch_selected(self, selected: bool) -> None:
        """Handle selection state change."""
        if selected:
            self.add_class("selected")
        else:
            self.remove_class("selected")

    def on_click(self, event: events.Click) -> None:
        """Handle click event."""
        event.stop()
        if self._on_select:
            self._on_select(self.agent)


class AgentGrid(ScrollableContainer):
    """Grid container for agent cards."""

    DEFAULT_CSS = """
    AgentGrid {
        height: 100%;
        padding: 1;
    }
    """

    def __init__(
        self,
        agents: List[AgentInfo],
        on_select: Optional[Callable[[AgentInfo], None]] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.agents = agents
        self._on_select = on_select
        self._selected_index = 0

    def compose(self) -> ComposeResult:
        """Compose the agent grid."""
        for i, agent in enumerate(self.agents):
            yield AgentCard(
                agent,
                on_select=self._on_select,
                id=f"agent-card-{i}",
            )

    def select_agent(self, index: int) -> None:
        """Select an agent by index."""
        if not self.agents:
            return

        # Clamp index
        index = max(0, min(index, len(self.agents) - 1))

        # Update selection
        old_card = self.query_one(f"#agent-card-{self._selected_index}", AgentCard)
        old_card.selected = False

        self._selected_index = index
        new_card = self.query_one(f"#agent-card-{self._selected_index}", AgentCard)
        new_card.selected = True
        new_card.focus()

    def get_selected_agent(self) -> Optional[AgentInfo]:
        """Get the currently selected agent."""
        if 0 <= self._selected_index < len(self.agents):
            return self.agents[self._selected_index]
        return None


class CategoryFilter(OptionList):
    """Category filter sidebar."""

    DEFAULT_CSS = """
    CategoryFilter {
        width: 20;
        height: 100%;
        border-right: solid #3f3f46;
        padding: 1;
    }
    """

    def __init__(self, categories: List[str], **kwargs):
        super().__init__(**kwargs)
        self.categories = ["all"] + categories

    def on_mount(self) -> None:
        """Mount the category list."""
        for category in self.categories:
            icon = CATEGORY_ICONS.get(category, "") if category != "all" else ""
            label = category.title()
            self.add_option(Option(f"{icon} {label}", id=category))


class AgentStoreScreen(Screen):
    """
    Full-screen agent store browser.

    Shows a grid of available agents with filtering,
    search, and installation capabilities.
    """

    BINDINGS = [
        Binding("j", "next_agent", "Next", show=True),
        Binding("k", "prev_agent", "Previous", show=True),
        Binding("enter", "launch_agent", "Launch", show=True),
        Binding("i", "install_agent", "Setup Guide", show=True),
        Binding("u", "uninstall_agent", "Uninstall", show=False),
        Binding("/", "focus_search", "Search", show=True),
        Binding("escape", "dismiss", "Back", show=True),
        Binding("r", "refresh", "Refresh", show=True),
    ]

    CSS = """
    AgentStoreScreen {
        background: #0a0a0a;
    }

    #store-header {
        height: 3;
        background: #18181b;
        padding: 0 1;
    }

    #store-title {
        color: #a855f7;
        text-style: bold;
    }

    #search-input {
        width: 40;
        margin-left: 2;
    }

    #store-body {
        height: 1fr;
    }

    #agent-detail {
        width: 30%;
        border-left: solid #3f3f46;
        padding: 1;
    }

    #detail-title {
        text-style: bold;
        color: #e4e4e7;
    }

    #detail-actions {
        margin-top: 2;
    }

    #detail-actions Button {
        margin-right: 1;
    }

    .action-button {
        min-width: 12;
    }

    .install-btn {
        background: #22c55e;
    }

    .launch-btn {
        background: #a855f7;
    }

    .uninstall-btn {
        background: #ef4444;
    }
    """

    def __init__(
        self,
        agents: Optional[List[AgentInfo]] = None,
        on_launch: Optional[Callable[[AgentInfo], None]] = None,
        on_install: Optional[Callable[[AgentInfo], None]] = None,
        on_uninstall: Optional[Callable[[AgentInfo], None]] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.agents = agents or []
        self._on_launch = on_launch
        self._on_install = on_install
        self._on_uninstall = on_uninstall
        self._selected_agent: Optional[AgentInfo] = None
        self._filter_category = "all"
        self._search_query = ""

    def compose(self) -> ComposeResult:
        """Compose the store screen."""
        yield Header()

        # Header with title and search
        with Horizontal(id="store-header"):
            yield Static(" Agent Store", id="store-title")
            yield Input(placeholder="Search agents...", id="search-input")

        # Main body
        with Horizontal(id="store-body"):
            # Category filter
            categories = list(set(a.category for a in self.agents))
            yield CategoryFilter(categories, id="category-filter")

            # Agent grid
            yield AgentGrid(
                self._get_filtered_agents(),
                on_select=self._on_agent_select,
                id="agent-grid",
            )

            # Detail panel
            with Vertical(id="agent-detail"):
                yield Static("Select an agent", id="detail-content")
                with Horizontal(id="detail-actions"):
                    yield Button("Launch", id="btn-launch", classes="action-button launch-btn")
                    yield Button(
                        " Setup Guide", id="btn-install", classes="action-button install-btn"
                    )

        yield Footer()

    def _get_filtered_agents(self) -> List[AgentInfo]:
        """Get agents filtered by category and search."""
        agents = self.agents

        # Filter by category
        if self._filter_category != "all":
            agents = [a for a in agents if a.category == self._filter_category]

        # Filter by search
        if self._search_query:
            query = self._search_query.lower()
            agents = [
                a
                for a in agents
                if query in a.name.lower()
                or query in a.description.lower()
                or any(query in tag.lower() for tag in a.tags)
            ]

        return agents

    def _on_agent_select(self, agent: AgentInfo) -> None:
        """Handle agent selection."""
        self._selected_agent = agent
        self._update_detail_panel()

    def _update_detail_panel(self) -> None:
        """Update the detail panel with selected agent."""
        detail = self.query_one("#detail-content", Static)

        if not self._selected_agent:
            detail.update("Select an agent")
            return

        agent = self._selected_agent
        status_style = STATUS_STYLES.get(agent.status, STATUS_STYLES[AgentStatus.AVAILABLE])

        content = Text()
        content.append(f"{agent.name}\n", style=f"bold {THEME['text']}")
        content.append(f"v{agent.version} by {agent.author}\n\n", style=THEME["muted"])
        content.append(f"{agent.description}\n\n", style=THEME["text"])
        content.append(
            f"Status: {status_style['icon']} {status_style['label']}\n", style=status_style["color"]
        )
        content.append(f"Category: {agent.category}\n", style=THEME["muted"])

        if agent.tags:
            content.append(f"Tags: {', '.join(agent.tags)}\n", style=THEME["dim"])

        if agent.downloads:
            content.append(f"Downloads: {agent.downloads:,}\n", style=THEME["muted"])

        if agent.rating:
            stars = "" * int(agent.rating) + "" * (5 - int(agent.rating))
            content.append(f"Rating: {stars}\n", style=THEME["warning"])

        detail.update(content)

        # Update buttons
        install_btn = self.query_one("#btn-install", Button)
        if agent.status == AgentStatus.INSTALLED:
            # Agent already installed - show uninstall option
            install_btn.label = " Uninstall"
            install_btn.remove_class("install-btn")
            install_btn.add_class("uninstall-btn")
        else:
            # Show setup guide (not auto-install)
            install_btn.label = " Setup Guide"
            install_btn.remove_class("uninstall-btn")
            install_btn.add_class("install-btn")

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input change."""
        if event.input.id == "search-input":
            self._search_query = event.value
            self._refresh_grid()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle category selection."""
        if event.option_list.id == "category-filter":
            self._filter_category = str(event.option.id)
            self._refresh_grid()

    def _refresh_grid(self) -> None:
        """Refresh the agent grid with current filters."""
        grid = self.query_one("#agent-grid", AgentGrid)
        grid.remove()

        new_grid = AgentGrid(
            self._get_filtered_agents(),
            on_select=self._on_agent_select,
            id="agent-grid",
        )

        body = self.query_one("#store-body", Horizontal)
        body.mount(new_grid, before=self.query_one("#agent-detail"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if not self._selected_agent:
            return

        if event.button.id == "btn-launch":
            self.action_launch_agent()
        elif event.button.id == "btn-install":
            if self._selected_agent.status == AgentStatus.INSTALLED:
                self.action_uninstall_agent()
            else:
                # Show setup guide (not auto-install)
                self.action_install_agent()

    def action_next_agent(self) -> None:
        """Select next agent."""
        grid = self.query_one("#agent-grid", AgentGrid)
        grid.select_agent(grid._selected_index + 1)
        agent = grid.get_selected_agent()
        if agent:
            self._on_agent_select(agent)

    def action_prev_agent(self) -> None:
        """Select previous agent."""
        grid = self.query_one("#agent-grid", AgentGrid)
        grid.select_agent(grid._selected_index - 1)
        agent = grid.get_selected_agent()
        if agent:
            self._on_agent_select(agent)

    def action_launch_agent(self) -> None:
        """Launch the selected agent."""
        if self._selected_agent and self._on_launch:
            self._on_launch(self._selected_agent)
            self.dismiss()

    def action_install_agent(self) -> None:
        """Show install guidance for the selected agent."""
        if self._selected_agent:
            # Show the install guidance panel (does NOT auto-install)
            self.app.push_screen(InstallGuidancePanel(self._selected_agent))

    def action_uninstall_agent(self) -> None:
        """Uninstall the selected agent."""
        if self._selected_agent and self._on_uninstall:
            self._on_uninstall(self._selected_agent)
            self._selected_agent.status = AgentStatus.AVAILABLE
            self._update_detail_panel()

    def action_focus_search(self) -> None:
        """Focus the search input."""
        self.query_one("#search-input", Input).focus()

    def action_refresh(self) -> None:
        """Refresh the agent list."""
        self._refresh_grid()

    def action_dismiss(self) -> None:
        """Close the store screen."""
        self.app.pop_screen()


# Helper function to create sample agents for testing
def create_sample_agents() -> List[AgentInfo]:
    """Create sample agents for testing."""
    return [
        AgentInfo(
            id="claude-code",
            name="Claude Code",
            description="Full-featured AI coding assistant with file editing, shell access, and code intelligence.",
            author="Anthropic",
            version="1.0.0",
            category="code",
            status=AgentStatus.INSTALLED,
            tags=["ai", "coding", "assistant"],
            downloads=50000,
            rating=4.8,
            install_command="curl -fsSL https://claude.ai/install.sh | bash && npm install -g @zed-industries/claude-code-acp",
            install_description="Install Claude Code + ACP adapter",
            run_command="claude-code-acp",
            requirements=["Node.js 18+", "npm"],
            documentation_url="https://claude.ai/code",
        ),
        AgentInfo(
            id="opencode",
            name="OpenCode",
            description="Open-source AI coding agent with ACP protocol support.",
            author="SST",
            version="0.5.0",
            category="code",
            status=AgentStatus.AVAILABLE,
            tags=["ai", "coding", "open-source"],
            downloads=10000,
            rating=4.5,
            install_command="npm i -g opencode-ai",
            install_description="Install OpenCode",
            run_command="opencode acp",
            requirements=["Node.js 18+", "npm"],
            documentation_url="https://opencode.ai/",
            repository="https://github.com/sst/opencode",
        ),
        AgentInfo(
            id="gemini-cli",
            name="Gemini CLI",
            description="Google's Gemini AI in your terminal with ACP support.",
            author="Google",
            version="1.0.0",
            category="code",
            status=AgentStatus.AVAILABLE,
            tags=["ai", "google", "gemini"],
            downloads=20000,
            rating=4.6,
            install_command="npm install -g @anthropic-ai/gemini-cli",
            install_description="Install Gemini CLI",
            run_command="gemini --experimental-acp",
            requirements=["Node.js 18+", "npm", "Google Cloud account"],
            documentation_url="https://ai.google.dev/gemini-api/docs",
        ),
        AgentInfo(
            id="codex",
            name="Codex",
            description="OpenAI's code generation agent with streaming terminal output.",
            author="OpenAI",
            version="1.0.0",
            category="code",
            status=AgentStatus.AVAILABLE,
            tags=["ai", "openai", "coding"],
            downloads=30000,
            rating=4.4,
            install_command="npm install -g @zed-industries/codex-acp",
            install_description="Install Codex ACP adapter",
            run_command="codex-acp",
            requirements=["Node.js 18+", "npm", "OpenAI API key"],
            documentation_url="https://openai.com/codex",
        ),
        AgentInfo(
            id="goose",
            name="Goose",
            description="Block's developer agent that automates engineering tasks.",
            author="Block",
            version="1.0.0",
            category="code",
            status=AgentStatus.AVAILABLE,
            tags=["ai", "automation", "coding"],
            downloads=15000,
            rating=4.3,
            install_command="pipx install goose-ai",
            install_description="Install Goose",
            run_command="goose",
            requirements=["Python 3.10+", "pipx"],
            documentation_url="https://github.com/block/goose",
            repository="https://github.com/block/goose",
        ),
    ]
