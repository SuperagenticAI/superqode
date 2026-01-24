"""SuperQode Textual widgets.

Core widgets are imported directly. QE-specific and advanced widgets
are available via lazy imports for performance.
"""

from superqode.widgets.status_bar import StatusBar
from superqode.widgets.slash_complete import SlashComplete
from superqode.widgets.prompt import SmartPrompt
from superqode.widgets.command_palette import CommandPalette
from superqode.widgets.agent_switcher import AgentSwitcher
from superqode.widgets.throbber import Throbber
from superqode.widgets.toast import Toast, ToastContainer

# Core widgets (always imported)
__all__ = [
    # Core widgets
    "StatusBar",
    "SlashComplete",
    "SmartPrompt",
    "CommandPalette",
    "AgentSwitcher",
    "Throbber",
    "Toast",
    "ToastContainer",
    # QE widgets (lazy loaded)
    "get_qe_dashboard",
    "get_agent_collab",
    "get_issue_timeline",
    "get_code_context",
    "get_animation_manager",
    # Advanced widgets (lazy loaded)
    "get_pty_shell",
    "get_permission_preview",
    "get_enhanced_toast",
    "get_mode_switcher",
    # TUI Enhancement widgets (lazy loaded)
    "get_rich_tool_display",
    "get_thinking_display",
    "get_response_display",
    "get_connection_status",
    "get_conversation_history",
    "get_enhanced_status_bar",
    # SuperQode unique widgets (lazy loaded)
    "get_superqode_display",
    "get_split_view",
    "get_resizable_sidebar",
    "get_sidebar_panels",
    "get_file_reference",
    "get_leader_key",
    # Unified output display (recommended for new code)
    "get_unified_output",
]


# Lazy loaders for QE widgets (avoid import overhead until needed)
def get_qe_dashboard():
    """Lazy load the QE Dashboard widget."""
    from superqode.widgets.qe_dashboard import QEDashboard, QualityMetric

    return QEDashboard, QualityMetric


def get_agent_collab():
    """Lazy load the Agent Collaboration view widget."""
    from superqode.widgets.agent_collab import AgentCollabView, AgentNode, AgentState

    return AgentCollabView, AgentNode, AgentState


def get_issue_timeline():
    """Lazy load the Issue Timeline widget."""
    from superqode.widgets.issue_timeline import (
        IssueTimeline,
        CompactIssueTimeline,
        DiscoveredIssue,
        IssueSeverity,
        IssueCategory,
    )

    return IssueTimeline, CompactIssueTimeline, DiscoveredIssue, IssueSeverity, IssueCategory


def get_code_context():
    """Lazy load the Code Context viewer widget."""
    from superqode.widgets.code_context import (
        CodeContextViewer,
        CompactCodeContext,
        CodeContext,
        CodeLine,
        LineType,
    )

    return CodeContextViewer, CompactCodeContext, CodeContext, CodeLine, LineType


def get_animation_manager():
    """Lazy load the Animation Manager."""
    from superqode.widgets.animation_manager import (
        AnimationManager,
        AnimationConfig,
        AnimatedWidget,
        ThrottledRefreshMixin,
    )

    return AnimationManager, AnimationConfig, AnimatedWidget, ThrottledRefreshMixin


def get_pty_shell():
    """Lazy load the PTY Shell widget."""
    from superqode.widgets.pty_shell import (
        PTYShell,
        PTYShellWidget,
        ShellManager,
    )

    return PTYShell, PTYShellWidget, ShellManager


def get_permission_preview():
    """Lazy load the Permission Preview widget."""
    from superqode.widgets.permission_preview import (
        PermissionPreview,
        PermissionPreviewScreen,
        PermissionContext,
        PreviewType,
        create_file_write_preview,
        create_command_preview,
    )

    return (
        PermissionPreview,
        PermissionPreviewScreen,
        PermissionContext,
        PreviewType,
        create_file_write_preview,
        create_command_preview,
    )


def get_enhanced_toast():
    """Lazy load the Enhanced Toast system."""
    from superqode.widgets.enhanced_toast import (
        ToastType,
        ToastConfig,
        ToastWidget,
        ToastContainer as EnhancedToastContainer,
        toast_success,
        toast_warning,
        toast_error,
        toast_info,
        toast_progress,
    )

    return (
        ToastType,
        ToastConfig,
        ToastWidget,
        EnhancedToastContainer,
        toast_success,
        toast_warning,
        toast_error,
        toast_info,
        toast_progress,
    )


def get_mode_switcher():
    """Lazy load the Mode Switcher widget."""
    from superqode.widgets.mode_switcher import (
        AppMode,
        ModeSwitcher,
        ModeIndicator,
        ModeTransition,
        MODES,
    )

    return AppMode, ModeSwitcher, ModeIndicator, ModeTransition, MODES


def get_rich_tool_display():
    """Lazy load the Rich Tool Display widgets."""
    from superqode.widgets.rich_tool_display import (
        ToolCallPanel,
        SingleToolDisplay,
        ToolCallData,
        ToolKind,
        ToolState,
        CompactToolIndicator,
        create_file_read_tool,
        create_file_write_tool,
        create_shell_tool,
        create_search_tool,
    )

    return (
        ToolCallPanel,
        SingleToolDisplay,
        ToolCallData,
        ToolKind,
        ToolState,
        CompactToolIndicator,
        create_file_read_tool,
        create_file_write_tool,
        create_shell_tool,
        create_search_tool,
    )


def get_thinking_display():
    """Lazy load the Thinking Display widgets."""
    from superqode.widgets.thinking_display import (
        ThinkingPanel,
        ExtendedThinkingPanel,
        ThinkingIndicator,
        ThoughtChunk,
        ThoughtType,
        UnifiedThinkingManager,
        ThinkingSource,
        ThinkingStats,
    )

    return (
        ThinkingPanel,
        ExtendedThinkingPanel,
        ThinkingIndicator,
        ThoughtChunk,
        ThoughtType,
        UnifiedThinkingManager,
        ThinkingSource,
        ThinkingStats,
    )


def get_response_display():
    """Lazy load the Response Display widgets."""
    from superqode.widgets.response_display import (
        ResponseDisplay,
        StreamingText,
        CodeBlockWidget,
        ParsedResponse,
        ResponseState,
    )

    return ResponseDisplay, StreamingText, CodeBlockWidget, ParsedResponse, ResponseState


def get_connection_status():
    """Lazy load the Connection Status widgets."""
    from superqode.widgets.connection_status import (
        ConnectionIndicator,
        ConnectionPanel,
        ModelSelector,
        ConnectionInfo,
        ConnectionType,
        ConnectionState,
        TokenUsage,
    )

    return (
        ConnectionIndicator,
        ConnectionPanel,
        ModelSelector,
        ConnectionInfo,
        ConnectionType,
        ConnectionState,
        TokenUsage,
    )


def get_conversation_history():
    """Lazy load the Conversation History widgets."""
    from superqode.widgets.conversation_history import (
        ConversationTimeline,
        MessageDetail,
        ConversationNavigator,
        HistoryMessage,
        MessageType,
    )

    return ConversationTimeline, MessageDetail, ConversationNavigator, HistoryMessage, MessageType


def get_enhanced_status_bar():
    """Lazy load the Enhanced Status Bar."""
    from superqode.widgets.enhanced_status_bar import (
        EnhancedStatusBar,
        MiniStatusIndicator,
        StatusBarState,
        AgentStatus,
        create_default_status_bar,
    )

    return (
        EnhancedStatusBar,
        MiniStatusIndicator,
        StatusBarState,
        AgentStatus,
        create_default_status_bar,
    )


def get_superqode_display():
    """Lazy load the SuperQode Display widgets (unique design system)."""
    from superqode.widgets.superqode_display import (
        EnhancedStatusHeader,
        EnhancedToolPanel,
        EnhancedThinkingBar,
        ToolStatus,
        AgentState,
        ToolCallInfo,
        SessionStats,
        show_agent_header,
        show_tool_call,
        show_thinking,
        show_response,
        show_completion_summary,
    )

    return (
        EnhancedStatusHeader,
        EnhancedToolPanel,
        EnhancedThinkingBar,
        ToolStatus,
        AgentState,
        ToolCallInfo,
        SessionStats,
        show_agent_header,
        show_tool_call,
        show_thinking,
        show_response,
        show_completion_summary,
    )


def get_split_view():
    """Lazy load the Split View widget."""
    from superqode.widgets.split_view import (
        SplitView,
        CodeViewer,
        TabBar,
        FileTab,
        SplitDivider,
    )

    return SplitView, CodeViewer, TabBar, FileTab, SplitDivider


def get_resizable_sidebar():
    """Lazy load the Resizable Sidebar components."""
    from superqode.widgets.resizable_sidebar import (
        ResizableDivider,
        ResizableSidebarContainer,
        SidebarTabBar,
    )

    return ResizableDivider, ResizableSidebarContainer, SidebarTabBar


def get_sidebar_panels():
    """Lazy load the Sidebar Panel widgets."""
    from superqode.widgets.sidebar_panels import (
        AgentPanel,
        ContextPanel,
        TerminalPanel,
        DiffPanel,
        HistoryPanel,
        AgentInfo,
        ContextFile,
        FileDiff,
        HistoryMessage,
    )

    return (
        AgentPanel,
        ContextPanel,
        TerminalPanel,
        DiffPanel,
        HistoryPanel,
        AgentInfo,
        ContextFile,
        FileDiff,
        HistoryMessage,
    )


def get_file_reference():
    """Lazy load the File Reference widgets."""
    from superqode.widgets.file_reference import (
        FileAutocomplete,
        FileReferenceInput,
        FileScanner,
        parse_file_references,
        expand_file_references,
        format_file_context,
    )

    return (
        FileAutocomplete,
        FileReferenceInput,
        FileScanner,
        parse_file_references,
        expand_file_references,
        format_file_context,
    )


def get_leader_key():
    """Lazy load the Leader Key widgets."""
    from superqode.widgets.leader_key import (
        LeaderKeyPopup,
        LeaderKeyMixin,
        LEADER_KEYS,
    )

    return LeaderKeyPopup, LeaderKeyMixin, LEADER_KEYS


def get_unified_output():
    """
    Lazy load the Unified Output Display.

    This is the recommended widget for displaying agent output.
    It works consistently across BYOK, ACP, and Local modes,
    and supports copy to clipboard.

    Usage:
        (
            UnifiedOutputDisplay,
            ThinkingSection,
            ResponseSection,
            OutputMode,
            OutputStats,
            copy_to_clipboard,
        ) = get_unified_output()

        # In your app
        output = UnifiedOutputDisplay(mode=OutputMode.BYOK)
        output.set_agent_info("Claude", "claude-3-opus")
        output.start_session()

        # Handle streaming
        output.start_thinking()
        output.append_thinking("Analyzing the code...")
        output.complete_thinking()

        output.start_response()
        output.append_response("Here's what I found...")
        output.complete_response(prompt_tokens=100, completion_tokens=500)
    """
    from superqode.widgets.unified_output import (
        UnifiedOutputDisplay,
        ThinkingSection,
        ResponseSection,
        OutputMode,
        OutputState,
        OutputStats,
        ThinkingEntry,
        Theme,
        CopyRequested,
        CopyComplete,
        copy_to_clipboard,
    )

    return (
        UnifiedOutputDisplay,
        ThinkingSection,
        ResponseSection,
        OutputMode,
        OutputState,
        OutputStats,
        ThinkingEntry,
        Theme,
        CopyRequested,
        CopyComplete,
        copy_to_clipboard,
    )
