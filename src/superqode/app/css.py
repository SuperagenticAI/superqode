"""
SuperQode App CSS Styles.
"""

APP_CSS = """
Screen { background: #000000; }

#main-grid { height: 100%; layout: horizontal; }

/* Sidebar - hidden by default */
#sidebar {
    width: 80;
    background: #000000;
    border-right: tall #1a1a1a;
    display: none;
}
#sidebar.visible {
    display: block;
}

/* Compact sidebar (tree only) */
#compact-sidebar {
    width: 32;
    background: #000000;
    border-right: tall #1a1a1a;
    display: none;
    padding: 1;
}
#compact-sidebar.visible { display: block; }
#sidebar-title { text-align: center; color: #a855f7; text-style: bold; margin-bottom: 1; }
#sidebar-tree { height: 1fr; background: #000000; }

/* Collapsible Sidebar (new) */
CollapsibleSidebar {
    width: 100%;
    height: 100%;
}

CollapsibleSidebar #file-search.-hidden {
    display: none;
}

CollapsibleSidebar Collapsible {
    border: none;
    background: #000000;
}

CollapsibleSidebar CollapsibleTitle {
    background: #0a0a0a;
    padding: 0 1;
}

CollapsibleSidebar CollapsibleTitle:hover {
    background: #1a1a1a;
}

/* Main content - Warp style layout */
#content { width: 1fr; layout: vertical; }

/* Status bar - ALWAYS visible at top, never hidden */
#status-bar { height: 2; min-height: 2; background: #0a0a0a; padding: 0 1; border-bottom: solid #27272a; }

/* Scanning line - shown at TOP when agent is thinking */
#thinking-wave { height: 1; width: 100%; margin: 0; padding: 0; display: none; }
#thinking-wave.visible { display: block; }

/* Scanning line - shown at BOTTOM when agent is thinking */
#thinking-wave-bottom { height: 1; width: 100%; margin: 0; padding: 0; display: none; }
#thinking-wave-bottom.visible { display: block; }

/* Conversation - main response area (expandable) - FULL WIDTH */
#conversation {
    height: 1fr;
    margin: 0;
    background: #000000;
    border: round #1a1a1a;
    padding: 0 1;
    overflow-x: hidden;
    width: 100%;
}
#log {
    height: 100%;
    background: #000000;
    color: #e4e4e7;
    overflow-x: hidden;
    overflow-y: auto;
    width: 100%;
}
ConversationLog {
    background: #000000;
    width: 100%;
    padding: 0;
    margin: 0;
}

/* Prompt area - at TOP (below SuperQode logo), hidden when agent is thinking */
#prompt-area { height: auto; padding: 0 1; background: #000000; margin-top: 0; border-bottom: solid #1a1a1a; }
#prompt-area.hidden { display: none; }
#mode-badge { height: auto; text-align: center; margin-bottom: 0; }
#input-box { height: 3; background: #000000; border: tall #1a1a1a; margin: 0 4; margin-top: 1; }
#input-box:focus-within { border: tall #a855f7; }
#prompt-symbol { width: 3; color: #ec4899; text-style: bold; padding: 0 1; }
#prompt-input { background: transparent; border: none; }
#hints { text-align: center; color: #52525b; height: 1; margin-top: 1; padding: 0; }

/* Streaming thinking indicator with changing text - shown when agent is thinking */
#streaming-thinking { height: auto; text-align: left; padding: 0 2; margin-bottom: 1; display: none; }
#streaming-thinking.visible { display: block; }


/* Enhanced sidebar styles */
EnhancedSidebar {
    width: 100%;
    height: 100%;
}

ColorfulDirectoryTree {
    background: #000000;
}

ColorfulDirectoryTree > .tree--guides {
    color: #1a1a1a;
}

ColorfulDirectoryTree > .tree--cursor {
    background: #3f3f46;
    color: #ec4899;
    text-style: bold;
    border-left: tall #a855f7;
}

ColorfulDirectoryTree:focus > .tree--cursor {
    background: #52525b;
    color: #ec4899;
    text-style: bold;
    border-left: tall #a855f7;
}

/* Resizable Sidebar Divider */
#sidebar-divider {
    width: 1;
    height: 100%;
    background: #1a1a1a;
}

#sidebar-divider:hover {
    background: #7c3aed;
}

#sidebar-divider.dragging {
    background: #a855f7;
}

#sidebar-divider.-hidden {
    display: none;
}

/* Panel Styles */
.panel-header {
    height: 2;
    background: #0a0a0a;
    border-bottom: solid #1a1a1a;
    padding: 0 1;
}

.panel-content {
    height: 1fr;
    background: #000000;
    padding: 1;
}

.panel-footer {
    height: 2;
    background: #0a0a0a;
    border-top: solid #1a1a1a;
    padding: 0 1;
}

.panel-item {
    height: auto;
    padding: 0 1;
    margin-bottom: 1;
}

.panel-item:hover {
    background: #0a0a0a;
}

.panel-item.selected {
    background: #7c3aed20;
    border-left: solid #7c3aed;
}

/* Agent Panel */
AgentPanel {
    height: 100%;
    background: #000000;
}

AgentPanel .stat-row {
    height: 1;
}

AgentPanel .stat-label {
    width: 12;
    color: #71717a;
}

AgentPanel .stat-value {
    width: 1fr;
    color: #e4e4e7;
}

/* Context Panel */
ContextPanel {
    height: 100%;
    background: #000000;
}

ContextPanel .context-file {
    height: 2;
    padding: 0 1;
}

ContextPanel .context-file:hover {
    background: #0a0a0a;
}

/* Terminal Panel */
TerminalPanel {
    height: 100%;
    background: #000000;
}

TerminalPanel #terminal-output {
    height: 1fr;
    background: #0c0c0c;
    padding: 1;
}

TerminalPanel #terminal-input Input {
    width: 100%;
    background: #0a0a0a;
    border: solid #1a1a1a;
}

TerminalPanel #terminal-input Input:focus {
    border: solid #7c3aed;
}

/* Diff Panel */
DiffPanel {
    height: 100%;
    background: #000000;
}

DiffPanel .diff-file {
    height: 2;
    padding: 0 1;
}

DiffPanel .diff-file:hover {
    background: #0a0a0a;
}

DiffPanel .diff-file.selected {
    background: #7c3aed20;
}

/* History Panel */
HistoryPanel {
    height: 100%;
    background: #000000;
}

HistoryPanel .history-message {
    height: auto;
    padding: 1;
    border-bottom: solid #0a0a0a;
}

HistoryPanel .history-message:hover {
    background: #0a0a0a;
}

/* Sidebar Tab Bar - Compact */
SidebarTabs {
    height: 2;
    width: 100%;
    background: #000000;
    border-bottom: solid #1a1a1a;
    overflow-x: auto;
}

SidebarTabs .tab {
    width: auto;
    min-width: 3;
    height: 100%;
    content-align: center middle;
    text-align: center;
    background: #000000;
    padding: 0 1;
    margin: 0 1;
}

/* Colorful icons - each tab has its own color */
SidebarTabs #tab-files {
    color: #3b82f6;
}

SidebarTabs #tab-code {
    color: #8b5cf6;
}

SidebarTabs #tab-changes {
    color: #10b981;
}

SidebarTabs #tab-search {
    color: #f59e0b;
}

SidebarTabs #tab-agent {
    color: #ec4899;
}

SidebarTabs #tab-context {
    color: #06b6d4;
}

SidebarTabs #tab-diff {
    color: #14b8a6;
}

SidebarTabs #tab-history {
    color: #a855f7;
}

SidebarTabs #tab-qe {
    color: #f59e0b;
}

SidebarTabs .tab:hover {
    text-style: bold;
}

SidebarTabs .tab.active {
    background: #27272a;
    border-bottom: tall #a855f7;
    text-style: bold;
}


/* Hidden view class for panel switching */
#files-view.-hidden,
#code-view.-hidden,
#changes-view.-hidden,
#search-view.-hidden,
#agent-view.-hidden,
#context-view.-hidden,
#terminal-view.-hidden,
#diff-view.-hidden,
#history-view.-hidden {
    display: none;
}
"""
