"""
Simple Desktop Notifications for SuperQode.

Provides optional desktop notifications for long-running tasks and QE runs.
Uses OS built-in tools without external dependencies:
- macOS: osascript (AppleScript)
- Linux: notify-send (libnotify)
- Windows: PowerShell toast notifications

All notifications are optional and fail silently if the system doesn't support them.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class NotificationLevel(Enum):
    """Notification urgency level."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class NotificationConfig:
    """Configuration for notifications."""

    enabled: bool = True
    sound: bool = True  # Play sound with notification (macOS only)
    timeout_seconds: int = 5  # Auto-dismiss timeout (Linux only)


# Default configuration
_config = NotificationConfig()


def configure_notifications(
    enabled: bool = True,
    sound: bool = True,
    timeout_seconds: int = 5,
) -> None:
    """
    Configure notification behavior.

    Args:
        enabled: Whether notifications are enabled.
        sound: Whether to play sound with notifications (macOS).
        timeout_seconds: Auto-dismiss timeout in seconds (Linux).
    """
    global _config
    _config = NotificationConfig(
        enabled=enabled,
        sound=sound,
        timeout_seconds=timeout_seconds,
    )


def is_notifications_supported() -> bool:
    """
    Check if desktop notifications are supported on this system.

    Returns:
        True if notifications are likely to work, False otherwise.
    """
    if sys.platform == "darwin":
        return True  # macOS always has osascript
    elif sys.platform == "linux":
        try:
            result = subprocess.run(
                ["which", "notify-send"],
                capture_output=True,
                timeout=2,
            )
            return result.returncode == 0
        except Exception:
            return False
    elif sys.platform == "win32":
        return True  # PowerShell is always available on modern Windows
    return False


def notify(
    title: str,
    message: str,
    level: NotificationLevel = NotificationLevel.INFO,
    subtitle: Optional[str] = None,
) -> bool:
    """
    Send a desktop notification.

    This function is synchronous and blocks briefly. For async contexts,
    use notify_async() instead.

    Args:
        title: Notification title (short, ~50 chars max).
        message: Notification body text.
        level: Notification urgency level (affects icon/sound on some systems).
        subtitle: Optional subtitle (macOS only).

    Returns:
        True if notification was sent successfully, False otherwise.
    """
    if not _config.enabled:
        return False

    try:
        if sys.platform == "darwin":
            return _notify_macos(title, message, subtitle, level)
        elif sys.platform == "linux":
            return _notify_linux(title, message, level)
        elif sys.platform == "win32":
            return _notify_windows(title, message, level)
        else:
            return False
    except Exception:
        # Notifications are optional - fail silently
        return False


async def notify_async(
    title: str,
    message: str,
    level: NotificationLevel = NotificationLevel.INFO,
    subtitle: Optional[str] = None,
) -> bool:
    """
    Send a desktop notification asynchronously.

    Non-blocking version of notify() for use in async contexts.

    Args:
        title: Notification title (short, ~50 chars max).
        message: Notification body text.
        level: Notification urgency level.
        subtitle: Optional subtitle (macOS only).

    Returns:
        True if notification was sent successfully, False otherwise.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, notify, title, message, level, subtitle)


def _notify_macos(
    title: str,
    message: str,
    subtitle: Optional[str],
    level: NotificationLevel,
) -> bool:
    """Send notification on macOS using osascript."""
    # Build AppleScript command
    script_parts = [f'display notification "{_escape_applescript(message)}"']
    script_parts.append(f'with title "{_escape_applescript(title)}"')

    if subtitle:
        script_parts.append(f'subtitle "{_escape_applescript(subtitle)}"')

    # Add sound based on level and config
    if _config.sound:
        sound_map = {
            NotificationLevel.INFO: "default",
            NotificationLevel.SUCCESS: "Glass",
            NotificationLevel.WARNING: "Basso",
            NotificationLevel.ERROR: "Sosumi",
        }
        sound = sound_map.get(level, "default")
        script_parts.append(f'sound name "{sound}"')

    script = " ".join(script_parts)

    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        timeout=5,
    )
    return result.returncode == 0


def _notify_linux(title: str, message: str, level: NotificationLevel) -> bool:
    """Send notification on Linux using notify-send."""
    # Map level to urgency
    urgency_map = {
        NotificationLevel.INFO: "normal",
        NotificationLevel.SUCCESS: "low",
        NotificationLevel.WARNING: "normal",
        NotificationLevel.ERROR: "critical",
    }
    urgency = urgency_map.get(level, "normal")

    # Map level to icon
    icon_map = {
        NotificationLevel.INFO: "dialog-information",
        NotificationLevel.SUCCESS: "emblem-ok-symbolic",
        NotificationLevel.WARNING: "dialog-warning",
        NotificationLevel.ERROR: "dialog-error",
    }
    icon = icon_map.get(level, "dialog-information")

    cmd = [
        "notify-send",
        "--urgency",
        urgency,
        "--icon",
        icon,
        "--expire-time",
        str(_config.timeout_seconds * 1000),  # Convert to ms
        "--app-name",
        "SuperQode",
        title,
        message,
    ]

    result = subprocess.run(cmd, capture_output=True, timeout=5)
    return result.returncode == 0


def _notify_windows(title: str, message: str, level: NotificationLevel) -> bool:
    """Send notification on Windows using PowerShell toast."""
    # PowerShell toast notification
    ps_script = f"""
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime] | Out-Null

    $template = @"
    <toast>
        <visual>
            <binding template="ToastText02">
                <text id="1">{_escape_xml(title)}</text>
                <text id="2">{_escape_xml(message)}</text>
            </binding>
        </visual>
    </toast>
"@

    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml($template)
    $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("SuperQode").Show($toast)
    """

    result = subprocess.run(
        ["powershell", "-Command", ps_script],
        capture_output=True,
        timeout=10,
    )
    return result.returncode == 0


def _escape_applescript(text: str) -> str:
    """Escape text for AppleScript string."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _escape_xml(text: str) -> str:
    """Escape text for XML."""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


# =============================================================================
# CONVENIENCE FUNCTIONS FOR COMMON NOTIFICATIONS
# =============================================================================


def notify_qe_complete(
    findings_count: int,
    duration_seconds: float,
    success: bool = True,
) -> bool:
    """
    Notify when a QE run completes.

    Args:
        findings_count: Number of findings discovered.
        duration_seconds: How long the QE run took.
        success: Whether the run completed successfully.

    Returns:
        True if notification was sent, False otherwise.
    """
    duration_str = f"{duration_seconds:.1f}s"
    if duration_seconds > 60:
        minutes = int(duration_seconds // 60)
        seconds = int(duration_seconds % 60)
        duration_str = f"{minutes}m {seconds}s"

    if success:
        if findings_count == 0:
            title = "QE Complete - No Issues!"
            message = f"All checks passed in {duration_str}"
            level = NotificationLevel.SUCCESS
        else:
            title = f"QE Complete - {findings_count} Finding{'s' if findings_count != 1 else ''}"
            message = f"Completed in {duration_str}. Review findings in SuperQode."
            level = NotificationLevel.WARNING
    else:
        title = "QE Run Failed"
        message = f"Run failed after {duration_str}. Check logs for details."
        level = NotificationLevel.ERROR

    return notify(title, message, level, subtitle="SuperQE")


def notify_task_complete(task_name: str, success: bool = True) -> bool:
    """
    Notify when a long-running task completes.

    Args:
        task_name: Name of the task that completed.
        success: Whether the task succeeded.

    Returns:
        True if notification was sent, False otherwise.
    """
    if success:
        return notify(
            "Task Complete",
            f"{task_name} finished successfully.",
            NotificationLevel.SUCCESS,
        )
    else:
        return notify(
            "Task Failed",
            f"{task_name} encountered an error.",
            NotificationLevel.ERROR,
        )


def notify_agent_ready(agent_name: str) -> bool:
    """
    Notify when an agent is ready for interaction.

    Args:
        agent_name: Name of the agent that's ready.

    Returns:
        True if notification was sent, False otherwise.
    """
    return notify(
        "Agent Ready",
        f"{agent_name} is connected and ready.",
        NotificationLevel.INFO,
    )


def notify_permission_required(action: str) -> bool:
    """
    Notify when user permission is required.

    Args:
        action: Description of the action requiring permission.

    Returns:
        True if notification was sent, False otherwise.
    """
    return notify(
        "Permission Required",
        f"SuperQode needs approval for: {action}",
        NotificationLevel.WARNING,
    )
