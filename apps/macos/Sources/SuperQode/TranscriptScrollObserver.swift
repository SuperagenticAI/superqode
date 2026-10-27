import AppKit
import SwiftUI

/// Observe scrolling within this transcript without intercepting native scrolling.
struct TranscriptScrollObserver: NSViewRepresentable {
  var onScroll: (Bool) -> Void
  func makeNSView(context: Context) -> TranscriptScrollViewObserver {
    let view = TranscriptScrollViewObserver()
    view.onScroll = onScroll
    return view
  }
  func updateNSView(_ view: TranscriptScrollViewObserver, context: Context) {
    view.onScroll = onScroll
  }
  static func dismantleNSView(_ view: TranscriptScrollViewObserver, coordinator: ()) {
    view.stopObserving()
  }
}

final class TranscriptScrollViewObserver: NSView {
  var onScroll: ((Bool) -> Void)?
  private var monitor: Any?
  func stopObserving() {
    if let monitor {
      NSEvent.removeMonitor(monitor)
      self.monitor = nil
    }
  }
  override func hitTest(_ point: NSPoint) -> NSView? { nil }
  override func viewDidMoveToWindow() {
    super.viewDidMoveToWindow()
    stopObserving()
    guard window != nil else { return }
    monitor = NSEvent.addLocalMonitorForEvents(matching: .scrollWheel) { [weak self] event in
      guard let self, let window = self.window, event.window === window,
        self.bounds.contains(self.convert(event.locationInWindow, from: nil)),
        event.scrollingDeltaY != 0
      else { return event }
      self.onScroll?(event.scrollingDeltaY > 0)
      return event
    }
  }
  deinit {
    if let monitor { DispatchQueue.main.async { NSEvent.removeMonitor(monitor) } }
  }
}
