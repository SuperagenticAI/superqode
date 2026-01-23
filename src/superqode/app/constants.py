"""
SuperQode App Constants - Theme, Icons, Colors, and Messages.
"""

# Bold ASCII art for SUPERQODE - thick and readable
ASCII_LOGO = """
░██████╗██╗░░░██╗██████╗░███████╗██████╗░░██████╗░░█████╗░██████╗░███████╗
██╔════╝██║░░░██║██╔══██╗██╔════╝██╔══██╗██╔═══██╗██╔══██╗██╔══██╗██╔════╝
╚█████╗░██║░░░██║██████╔╝█████╗░░██████╔╝██║░░░██║██║░░██║██║░░██║█████╗░░
░╚═══██╗██║░░░██║██╔═══╝░██╔══╝░░██╔══██╗██║▄▄░██║██║░░██║██║░░██║██╔══╝░░
██████╔╝╚██████╔╝██║░░░░░███████╗██║░░██║╚██████╔╝╚█████╔╝██████╔╝███████╗
╚═════╝░░╚═════╝░╚═╝░░░░░╚══════╝╚═╝░░╚═╝░╚══▀▀═╝░░╚════╝░╚═════╝░╚══════╝
"""

# Compact logo for header
COMPACT_LOGO = """╔═╗╦ ╦╔═╗╔═╗╦═╗╔═╗ ╔═╗╔╦╗╔═╗
╚═╗║ ║╠═╝║╣ ╠╦╝║╔╬╗║ ║ ║║║╣
╚═╝╚═╝╩  ╚═╝╩╚═╚╝╚╝╚═╝═╩╝╚═╝"""

TAGLINE_PART1 = "Orchestrate Coding Agents"
TAGLINE_PART2 = "Automate Your SDLC"

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
    "dev": "💻",
    "qa": "🧪",
    "devops": "⚙️",
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

AGENT_COLORS = {
    "claude": "#d97706",
    "opencode": "#22c55e",
    "codex": "#10b981",
    "gemini": "#4285f4",
    "goose": "#8b5cf6",
    "kimi": "#f43f5e",
    "augment": "#06b6d4",
    "openhands": "#f97316",
}

# Unique meaningful icons for each agent
AGENT_ICONS = {
    "claude": "🧡",  # Orange heart - Anthropic's warm AI
    "opencode": "🌿",  # Seedling - open source growth
    "codex": "📜",  # Scroll - OpenAI codex knowledge
    "gemini": "✨",  # Sparkles - Google Gemini's dual nature
    "goose": "🦆",  # Duck - Block's Goose (close cousin)
    "kimi": "🌸",  # Cherry blossom - Moonshot AI's Kimi (Asian origin)
    "augment": "🔮",  # Crystal ball - Augment's AI vision
    "openhands": "🤝",  # Handshake - OpenHands collaboration
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
    ":help",
    ":clear",
    ":exit",
    ":quit",
    ":dev fullstack",
    ":dev frontend",
    ":dev backend",
    ":qe fullstack",
    ":qe unit_tester",
    ":qe api_tester",
    ":devops fullstack",
    ":devops cicd_engineer",
    ":agents connect",
    ":agents connect opencode",
    ":agents list",
    ":agents install",
    ":agents model",
    ":providers list",
    ":providers use",
    ":providers show",
    ":roles",
    ":team",
    ":handoff",
    ":context",
    ":disconnect",
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
    ":diff",
    ":diff split",
    ":diff unified",
    ":plan",
    ":plan clear",
    ":undo",
    ":history",
    ":history clear",
    # File viewer commands
    ":view",
    ":view info",
    ":search",
    # Copy/Open commands
    ":copy",
    ":open",
    # MCP commands
    ":mcp list",
    ":mcp status",
    ":mcp tools",
    ":mcp connect",
    ":mcp disconnect",
    # Approval mode commands
    ":mode auto",
    ":mode ask",
    ":mode deny",
    ":mode",
]
