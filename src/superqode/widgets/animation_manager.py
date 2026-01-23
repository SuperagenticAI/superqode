"""
Animation Manager - Performance-Conscious Animation Control.

Provides centralized control for TUI animations to prevent
performance issues from multiple concurrent animations.

Features:
- Global frame rate limiting
- Focus-aware animation pausing
- Low-power mode support
- Batched updates for multiple animated widgets
"""

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set
from weakref import WeakSet

from textual.app import App
from textual.timer import Timer
from textual.widget import Widget


@dataclass
class AnimationConfig:
    """Configuration for animation behavior."""

    max_fps: int = 10  # Maximum frames per second
    pause_on_blur: bool = True  # Pause when app loses focus
    low_power_mode: bool = False  # Reduce animations for battery
    batch_updates: bool = True  # Batch widget updates together

    @property
    def frame_interval(self) -> float:
        """Get interval between frames in seconds."""
        return 1.0 / self.max_fps


class AnimationManager:
    """Central manager for TUI animations.

    Controls animation timing across multiple widgets to prevent
    performance degradation from too many concurrent animations.

    Usage:
        # In your App class
        class MyApp(App):
            def on_mount(self):
                self.animation_manager = AnimationManager(self)
                self.animation_manager.start()

        # In animated widgets
        class MyWidget(Static):
            def on_mount(self):
                app = self.app
                if hasattr(app, 'animation_manager'):
                    app.animation_manager.register(self, self._animate)

            def _animate(self, frame: int) -> None:
                # Update animation state
                self.refresh()
    """

    def __init__(
        self,
        app: App,
        config: Optional[AnimationConfig] = None,
    ):
        self.app = app
        self.config = config or AnimationConfig()

        # Registered widgets and their callbacks
        self._widgets: WeakSet[Widget] = WeakSet()
        self._callbacks: Dict[int, Callable[[int], None]] = {}

        # State
        self._timer: Optional[Timer] = None
        self._frame: int = 0
        self._running: bool = False
        self._focused: bool = True
        self._last_tick: float = 0.0

        # Batching
        self._pending_refreshes: Set[Widget] = set()

    @property
    def is_running(self) -> bool:
        """Check if animation manager is running."""
        return self._running

    @property
    def current_frame(self) -> int:
        """Get the current animation frame number."""
        return self._frame

    @property
    def should_animate(self) -> bool:
        """Check if animations should run right now."""
        if self.config.low_power_mode:
            return False
        if self.config.pause_on_blur and not self._focused:
            return False
        return self._running

    def register(
        self,
        widget: Widget,
        callback: Callable[[int], None],
    ) -> None:
        """Register a widget for animation updates.

        Args:
            widget: The widget to animate
            callback: Called each frame with frame number
        """
        self._widgets.add(widget)
        self._callbacks[id(widget)] = callback

    def unregister(self, widget: Widget) -> None:
        """Unregister a widget from animation updates."""
        self._widgets.discard(widget)
        self._callbacks.pop(id(widget), None)
        self._pending_refreshes.discard(widget)

    def start(self) -> None:
        """Start the animation manager."""
        if self._running:
            return

        self._running = True
        self._last_tick = time.monotonic()

        # Create timer for animation ticks
        self._timer = self.app.set_interval(
            self.config.frame_interval,
            self._tick,
        )

    def stop(self) -> None:
        """Stop the animation manager."""
        self._running = False
        if self._timer:
            self._timer.stop()
            self._timer = None

    def pause(self) -> None:
        """Pause animations (e.g., when app loses focus)."""
        self._focused = False

    def resume(self) -> None:
        """Resume animations (e.g., when app gains focus)."""
        self._focused = True

    def set_low_power(self, enabled: bool) -> None:
        """Enable/disable low power mode."""
        self.config.low_power_mode = enabled

    def request_refresh(self, widget: Widget) -> None:
        """Request a refresh for a widget (batched if enabled)."""
        if self.config.batch_updates:
            self._pending_refreshes.add(widget)
        else:
            widget.refresh()

    def _tick(self) -> None:
        """Called each animation frame."""
        if not self.should_animate:
            return

        self._frame += 1
        current_time = time.monotonic()

        # Call all registered callbacks
        dead_widgets = []
        for widget in list(self._widgets):
            if not widget.is_attached:
                dead_widgets.append(widget)
                continue

            callback = self._callbacks.get(id(widget))
            if callback:
                try:
                    callback(self._frame)
                except Exception:
                    # Don't let one widget break others
                    dead_widgets.append(widget)

        # Cleanup dead widgets
        for widget in dead_widgets:
            self.unregister(widget)

        # Flush batched refreshes
        if self.config.batch_updates and self._pending_refreshes:
            for widget in self._pending_refreshes:
                if widget.is_attached:
                    widget.refresh()
            self._pending_refreshes.clear()

        self._last_tick = current_time


class AnimatedWidget(Widget):
    """Base class for widgets that participate in managed animations.

    Automatically registers with the app's AnimationManager if present.

    Subclasses should override `on_animation_frame()` to update state.
    """

    def on_mount(self) -> None:
        """Register with animation manager when mounted."""
        super().on_mount()
        self._register_animation()

    def on_unmount(self) -> None:
        """Unregister from animation manager when unmounted."""
        self._unregister_animation()
        super().on_unmount()

    def _register_animation(self) -> None:
        """Register with the app's animation manager."""
        app = self.app
        if hasattr(app, "animation_manager"):
            app.animation_manager.register(self, self.on_animation_frame)

    def _unregister_animation(self) -> None:
        """Unregister from the app's animation manager."""
        app = self.app
        if hasattr(app, "animation_manager"):
            app.animation_manager.unregister(self)

    def on_animation_frame(self, frame: int) -> None:
        """Called each animation frame.

        Override this method to update animation state.
        Call self.refresh() when visual update is needed.

        Args:
            frame: The current frame number
        """
        pass


class ThrottledRefreshMixin:
    """Mixin that provides throttled refresh capability.

    Use this to prevent excessive refreshes in widgets that
    receive rapid updates.

    Usage:
        class MyWidget(ThrottledRefreshMixin, Static):
            def update_content(self, data):
                self._data = data
                self.throttled_refresh()
    """

    _throttle_interval: float = 0.05  # 50ms minimum between refreshes
    _last_refresh: float = 0.0
    _refresh_pending: bool = False
    _refresh_timer: Optional[Timer] = None

    def throttled_refresh(self) -> None:
        """Request a throttled refresh."""
        current = time.monotonic()
        elapsed = current - self._last_refresh

        if elapsed >= self._throttle_interval:
            # Enough time has passed, refresh immediately
            self._last_refresh = current
            self.refresh()
        elif not self._refresh_pending:
            # Schedule a refresh for later
            self._refresh_pending = True
            remaining = self._throttle_interval - elapsed

            # Use call_later if available (Textual widget)
            if hasattr(self, "call_later"):
                self.call_later(self._do_throttled_refresh, delay=remaining)

    def _do_throttled_refresh(self) -> None:
        """Execute the pending throttled refresh."""
        self._refresh_pending = False
        self._last_refresh = time.monotonic()
        self.refresh()
