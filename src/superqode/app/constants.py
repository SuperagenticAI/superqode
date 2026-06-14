"""
SuperQode App Constants - Theme, Icons, Colors, and Messages.
"""

# Clean ASCII art for SUPERQODE - Standard style (upright, thin)
ASCII_LOGO = """
 ____  _   _ ____  _____ ____   ___    ___  ____  _____
/ ___|| | | |  _ \\| ____|  _ \\ / _ \\  / _ \\|  _ \\| ____|
\\___ \\| | | | |_) |  _| | |_) | | | || | | | | | |  _|
 ___) | |_| |  __/| |___|  _ <| |_| || |_| | |_| | |___
|____/ \\___/|_|   |_____|_| \\_\\\\__\\_\\ \\___/|____/|_____|
"""

# Compact logo for header
COMPACT_LOGO = """ ____  _   _ ____  _____ ____   ___    ___  ____  _____
|____/ \\___/|_|   |_____|_| \\_\\\\__\\_\\ \\___/|____/|_____|"""

# Welcome subtitle: differentiators (line 1) + local-model emphasis (line 2).
TAGLINE_PART1 = "ACP MCP A2A  ·  Local BYOK SDKs  ·  Bring Your Own Harness"
TAGLINE_PART2 = "Optimized for Local Models"

# Normal purple → pink → orange gradient for ASCII logo
GRADIENT = ["#7c3aed", "#a855f7", "#c084fc", "#ec4899", "#f97316", "#fb923c"]

# Rainbow gradient for animations
RAINBOW = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#06b6d4", "#3b82f6", "#8b5cf6", "#ec4899"]

THEME = {
    "bg": "#000000",
    "surface": "#000000",
    "surface2": "#0a0a0a",
    "border": "#1a1a1a",
    "border_active": "#2a2a2a",
    "purple": "#a855f7",
    "magenta": "#d946ef",
    "pink": "#ec4899",
    "rose": "#fb7185",
    "orange": "#f97316",
    "gold": "#fbbf24",
    "yellow": "#eab308",
    "cyan": "#06b6d4",
    "teal": "#14b8a6",
    "green": "#22c55e",
    "success": "#22c55e",
    "error": "#ef4444",
    "warning": "#f59e0b",
    "text": "#e4e4e7",
    "muted": "#71717a",
    "dim": "#52525b",
}

# Rich emoji set for different contexts
ICONS = {
    # Status
    "done": "✓",
    "pending": "○",
    "active": "●",
    "error": "✗",
    "warning": "⚠",
    "success": "✅",
    "fail": "❌",
    "loading": "◌",
    # Navigation
    "home": "🏠",
    "back": "←",
    "forward": "→",
    "up": "↑",
    "down": "↓",
    # Actions
    "run": "▶",
    "stop": "■",
    "pause": "⏸",
    "refresh": "🔄",
    "search": "🔍",
    # Objects
    "file": "📄",
    "folder": "📁",
    "code": "💻",
    "terminal": "🖥️",
    "shell": "$",
    "link": "🔗",
    "key": "🔑",
    "lock": "🔒",
    "unlock": "🔓",
    # Team & Agents
    "team": "👥",
    "robot": "🤖",
    "brain": "🧠",
    "qa": "🧪",
    "user": "👤",
    "agent": "🤖",
    # Communication
    "task": "📋",
    "handoff": "🔄",
    "context": "📎",
    "message": "💬",
    "send": "📤",
    "receive": "📥",
    "chat": "💭",
    # Effects
    "spark": "✨",
    "magic": "🪄",
    "rocket": "🚀",
    "crystal": "🔮",
    "zap": "⚡",
    "bulb": "💡",
    "target": "🎯",
    "fire": "🔥",
    "star": "⭐",
    "gem": "💎",
    "crown": "👑",
    "trophy": "🏆",
    # Emotions
    "heart": "💜",
    "wave": "👋",
    "eyes": "👀",
    "think": "🤔",
    "celebrate": "🎉",
    "cool": "😎",
    "thumbsup": "👍",
    # Technical
    "api": "🔌",
    "database": "🗄️",
    "cloud": "☁️",
    "server": "🖥️",
    "git": "📦",
    "docker": "🐳",
    "test": "🧪",
    "bug": "🐛",
    # Help
    "help": "❓",
    "info": "ℹ️",
    "tip": "💡",
    "exit": "👋",
}

# 14 Official ACP Agents - Colors
AGENT_COLORS = {
    # Tier 1 - Major Agents
    "gemini": "#4285f4",  # Google Blue
    "claude": "#d97706",  # Anthropic Orange
    "claude-code": "#d97706",  # Anthropic Orange
    "codex": "#10b981",  # Green
    "junie": "#fe315d",  # JetBrains Pink
    "goose": "#8b5cf6",  # Block Purple
    "kimi": "#5b21b6",  # Moonshot Deep Purple
    "opencode": "#22c55e",  # Open Source Green
    # Tier 2 - Community Agents
    "stakpak": "#0ea5e9",  # Sky Blue
    "vtcode": "#f59e0b",  # Amber
    "auggie": "#ec4899",  # Pink
    "code-assistant": "#f97316",  # Rust Orange
    "cagent": "#6366f1",  # Indigo
    "fast-agent": "#14b8a6",  # Teal
    "llmling-agent": "#a855f7",  # Purple
}

# 14 Official ACP Agents - Icons
AGENT_ICONS = {
    # Tier 1 - Major Agents
    "gemini": "✨",  # Sparkles - Google Gemini's multimodal nature
    "claude": "🧡",  # Orange heart - Anthropic's warm AI
    "claude-code": "🧡",  # Orange heart - Anthropic's warm AI
    "codex": "📜",  # Scroll
    "junie": "🧠",  # Brain - JetBrains intelligence
    "goose": "🦆",  # Duck - Block's Goose
    "kimi": "🌙",  # Moon - Moonshot AI's Kimi
    "opencode": "🌿",  # Seedling - open source growth
    # Tier 2 - Community Agents
    "stakpak": "📦",  # Package - code packages
    "vtcode": "⚡",  # Lightning - versatile & fast
    "auggie": "🔮",  # Crystal ball - Augment's AI vision
    "code-assistant": "🦀",  # Crab - Rust language
    "cagent": "🤖",  # Robot - multi-agent orchestration
    "fast-agent": "🚀",  # Rocket - fast workflows
    "llmling-agent": "🔗",  # Link - framework connections
}

# Rich thinking messages with emojis - FUN & ENGAGING!
THINKING_MSGS = [
    # Classic thinking
    ("🧠 Analyzing your request", "brain"),
    ("🔍 Understanding context", "search"),
    ("💭 Thinking deeply", "think"),
    ("⚙️ Processing information", "gear"),
    # Fun & playful
    ("🎪 Juggling possibilities", "circus"),
    ("🎨 Painting a solution", "art"),
    ("🧩 Piecing together the puzzle", "puzzle"),
    ("🎭 Getting into character", "theater"),
    ("🎲 Rolling for initiative", "dice"),
    ("🎸 Jamming on your code", "music"),
    ("🎬 Directing the scene", "movie"),
    ("🎡 Spinning up ideas", "wheel"),
    # Food & cooking
    ("👨‍🍳 Cooking up something special", "chef"),
    ("🍳 Frying some fresh code", "cooking"),
    ("🥘 Simmering the solution", "stew"),
    ("🍕 Serving hot code", "pizza"),
    ("☕ Brewing the perfect response", "coffee"),
    # Space & science
    ("🚀 Launching into action", "rocket"),
    ("🌟 Aligning the stars", "stars"),
    ("🔭 Scanning the codeverse", "telescope"),
    ("⚛️ Splitting atoms of logic", "atom"),
    ("🌌 Exploring the galaxy", "galaxy"),
    ("🛸 Beaming down answers", "ufo"),
    # Magic & fantasy
    ("🪄 Casting a spell", "magic"),
    ("🔮 Consulting the crystal ball", "crystal"),
    ("✨ Sprinkling some magic", "sparkle"),
    ("🧙 Wizarding up a solution", "wizard"),
    ("🦄 Summoning unicorn power", "unicorn"),
    ("🐉 Awakening the code dragon", "dragon"),
    # Tech & coding
    ("💻 Compiling thoughts", "computer"),
    ("🔧 Tightening the bolts", "wrench"),
    ("⚡ Supercharging neurons", "lightning"),
    ("🔥 Firing up the engines", "fire"),
    ("💡 Light bulb moment incoming", "bulb"),
    ("🎯 Locking onto target", "target"),
    # Nature & animals
    ("🐝 Busy as a bee", "bee"),
    ("🦊 Being clever like a fox", "fox"),
    ("🐙 Multitasking like an octopus", "octopus"),
    ("🦅 Eagle-eye analyzing", "eagle"),
    ("🐢 Slow and steady wins", "turtle"),
    # Sports & action
    ("🏃 Sprinting to the finish", "runner"),
    ("🎳 Bowling a strike", "bowling"),
    ("🏄 Riding the code wave", "surf"),
    ("⛷️ Skiing through logic", "ski"),
    ("🎿 Slaloming past bugs", "slalom"),
    # Building & crafting
    ("🏗️ Constructing the answer", "construction"),
    ("🧱 Building brick by brick", "bricks"),
    ("🪚 Carving out a solution", "saw"),
    ("🎨 Masterpiece in progress", "palette"),
    ("📐 Measuring twice, coding once", "ruler"),
    # Celebration vibes
    ("🎉 Party in the processor", "party"),
    ("🎊 Confetti of creativity", "confetti"),
    ("🥳 Getting excited about this", "celebrate"),
    ("💃 Dancing through the code", "dance"),
    ("🕺 Grooving to the algorithm", "groove"),
]

# Commands for autocompletion - ordered by priority (most common first)
COMMANDS = [
    ":connect",
    ":connect codex",
    ":connect claude",
    ":connect antigravity",
    ":connect byok",
    ":connect local",
    ":connect acp",
    ":claude",
    ":claude status",
    ":claude model",
    ":claude permission",
    ":claude sessions",
    ":claude commands",
    ":claude review",
    ":antigravity",
    ":antigravity status",
    ":antigravity migrate",
    ":antigravity launch",
    ":agy",
    ":exit",
    ":quit",
    ":help",
    ":vim",
    ":vim on",
    ":vim off",
    ":set vim",
    ":set novim",
    ":w",
    ":e",
    ":ls",
    ":grep",
    ":clear",
    ":agents connect",
    ":agents connect opencode",
    ":agents list",
    ":agents install",
    ":agents model",
    ":providers list",
    ":providers free",
    ":providers free --live",
    ":providers free --live openrouter",
    ":providers free --live models-dev",
    ":providers free --live litellm",
    ":providers use",
    ":providers show",
    ":context",
    ":disconnect",
    # Runtime backend selection (see ':runtime list' for status)
    ":runtime",
    ":runtime list",
    ":runtime builtin",
    ":runtime adk",
    ":runtime openai-agents",
    ":runtime pydanticai",
    ":runtime codex-sdk",
    ":codex",
    ":codex status",
    ":codex models",
    ":codex model",
    ":codex effort",
    ":codex sandbox",
    ":codex review",
    ":codex compact",
    ":codex thread",
    ":codex sessions",
    ":codex resume",
    ":codex fork",
    ":codex rename",
    ":codex archive",
    ":codex account",
    ":codex logout",
    ":files",
    ":find",
    ":sidebar",
    ":toggle_thinking",
    ":home",
    # Init command
    ":init",
    # Coding agent commands
    ":approve",
    ":approve all",
    ":reject",
    ":reject all",
    ":permissions",
    ":policy",
    ":diff",
    ":diff files",
    ":diff split",
    ":diff unified",
    ":plan",
    ":plan on",
    ":plan off",
    ":plan status",
    ":plan run",
    ":plan approve",
    ":plan edit",
    ":plan review",
    ":plan reject",
    ":plan clear",
    ":undo",
    ":history",
    ":history clear",
    ":transcript",
    ":timeline",
    ":rewind",
    ":tree",
    ":share",
    ":share create",
    ":share export",
    ":share import",
    ":share list",
    ":share revoke",
    ":trust",
    ":trust status",
    ":trust yes",
    ":trust no",
    ":trust doctor",
    ":theme",
    ":export",
    ":export html",
    ":export markdown",
    ":export json",
    ":compare",
    ":sandbox",
    ":paste",
    ":queue",
    ":queue clear",
    ":stash",
    ":stash list",
    ":stash clear",
    ":session",
    ":session rename",
    ":update",
    # File viewer commands
    ":view",
    ":view info",
    ":search",
    ":tools",
    ":tools minimal",
    ":tools standard",
    ":tools full",
    ":plugins",
    ":plugins doctor",
    ":plugins add",
    ":plugins enable",
    ":plugins disable",
    ":memory",
    ":memory status",
    ":memory providers",
    ":memory doctor",
    ":memory remember",
    ":memory search",
    ":memory forget",
    ":memory export",
    ":local",
    ":local doctor",
    ":local packs",
    ":skills",
    ":skills list",
    ":skills info",
    ":skills search",
    ":skills add",
    ":skills import",
    ":skills doctor",
    ":skills enable",
    ":skills disable",
    ":skills remove",
    ":recipes",
    ":recipes list",
    ":recipe",
    ":recipe list",
    ":recipe info",
    ":recipe run",
    ":recipe doctor",
    ":harness",
    ":harness inspect",
    ":harness doctor",
    ":harness graph",
    ":harness replay",
    ":harness fork",
    ":harness evidence",
    ":harness events",
    ":harness runs",
    ":harness templates",
    ":workflow",
    ":workflow status",
    ":workflow presets",
    ":workflow preview",
    ":workflow doctor",
    ":workflow run",
    ":attach",
    ":attach list",
    ":attach remove",
    ":attach clear",
    ":prompt",
    "/sessions",
    "/resume",
    "/fork",
    "/compact",
    # Copy/Open commands
    ":copy",
    ":copy response",
    ":copy transcript",
    ":select",
    ":select response",
    ":select transcript",
    ":open",
    # MCP commands
    ":mcp list",
    ":mcp status",
    ":mcp tools",
    ":mcp resources",
    ":mcp prompts",
    ":mcp connect",
    ":mcp disconnect",
    ":mcp reconnect",
    ":mcp add",
    ":mcp doctor",
    ":mcp attach",
    ":model",
    ":model doctor",
    ":model switch",
    ":model reasoning",
    ":model temperature",
    ":doctor tui",
    # Approval mode commands
    ":mode auto",
    ":mode ask",
    ":mode deny",
    ":mode",
]
