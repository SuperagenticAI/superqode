import AppKit
import SwiftUI

private struct DialogCloseKey: EnvironmentKey {
  static let defaultValue: (() -> Void)? = nil
}
extension EnvironmentValues {
  var dialogClose: (() -> Void)? {
    get { self[DialogCloseKey.self] }
    set { self[DialogCloseKey.self] = newValue }
  }
}

/// Preserve dismiss() in both native dialogs and any standard SwiftUI presentation.
@propertyWrapper struct DialogDismiss: DynamicProperty {
  @Environment(\.dialogClose) private var close
  @Environment(\.dismiss) private var systemDismiss
  var wrappedValue: () -> Void { close ?? { systemDismiss() } }
}

extension View {
  func centeredDialog<Dialog: View>(
    isPresented: Binding<Bool>, title: String = "SuperQode",
    @ViewBuilder content: @escaping () -> Dialog
  ) -> some View {
    background(
      DialogAnchor(isPresented: isPresented, title: title, dialog: AnyView(content()))
        .frame(width: 0, height: 0).allowsHitTesting(false).accessibilityHidden(true))
  }
}

private struct DialogAnchor: NSViewRepresentable {
  @Binding var isPresented: Bool
  let title: String
  let dialog: AnyView
  func makeCoordinator() -> CenteredDialogController { CenteredDialogController() }
  func makeNSView(context: Context) -> DialogAnchorView {
    let view = DialogAnchorView()
    view.changedWindow = { [weak controller = context.coordinator] in controller?.schedule() }
    return view
  }
  func updateNSView(_ view: DialogAnchorView, context: Context) {
    context.coordinator.anchor = view
    context.coordinator.binding = $isPresented
    context.coordinator.title = title
    context.coordinator.content = AnyView(dialog.environment(\.self, context.environment))
    context.coordinator.schedule()
  }
  static func dismantleNSView(_ view: DialogAnchorView, coordinator: CenteredDialogController) {
    view.changedWindow = nil
    coordinator.close()
  }
}

private final class CenteredPanel: NSPanel {
  override func cancelOperation(_ sender: Any?) { performClose(sender) }
}

private final class DialogAnchorView: NSView {
  var changedWindow: (() -> Void)?
  override func viewDidMoveToWindow() {
    super.viewDidMoveToWindow()
    changedWindow?()
  }
}

/// A native modal session keeps background actions blocked without blocking the
/// main actor that loads Connect, streams sign-in progress and cancels workers.
@MainActor final class CenteredDialogController: NSObject, NSWindowDelegate {
  weak var anchor: NSView?
  var binding: Binding<Bool>?
  var content = AnyView(EmptyView())
  var title = "SuperQode"
  private(set) var panel: NSPanel?
  private var session: NSApplication.ModalSession?
  private var timer: Timer?
  private var scheduled = false
  private var closing = false
  private weak var parentWindow: NSWindow?
  private var presentationScreen: NSScreen?
  private var positioning = false
  private var firstModalPass = true
  private var positionedSize: NSSize?
  private var positionedDisplay: NSRect?

  static func centeredFrame(size: NSSize, visibleFrame: NSRect) -> NSRect {
    NSRect(
      x: visibleFrame.midX - size.width / 2,
      y: visibleFrame.midY - size.height / 2, width: size.width, height: size.height)
  }
  func schedule() {
    guard !scheduled else { return }
    scheduled = true
    DispatchQueue.main.async { [weak self] in
      guard let self else { return }
      self.scheduled = false
      self.synchronize()
    }
  }
  private func synchronize() {
    guard binding?.wrappedValue == true else {
      close()
      return
    }
    if let panel {
      (panel.contentView as? NSHostingView<AnyView>)?.rootView = hostedContent
      schedulePosition()
      return
    }
    guard let parent = anchor?.window, parent.isVisible else { return }
    present(parent: parent)
  }
  private var hostedContent: AnyView {
    AnyView(content.environment(\.dialogClose, { [weak self] in self?.close() }))
  }
  func present(parent: NSWindow) {
    guard panel == nil, let screen = parent.screen ?? NSScreen.main else { return }
    parentWindow = parent
    presentationScreen = screen
    firstModalPass = true
    let hosting = NSHostingView(rootView: hostedContent)
    hosting.layoutSubtreeIfNeeded()
    let desired = hosting.fittingSize
    let available = screen.visibleFrame.insetBy(dx: 24, dy: 12)
    // Include native title-bar height when sizing against the actual display.
    let contentSize = NSSize(
      width: min(max(360, desired.width), available.width),
      height: min(max(180, desired.height), max(180, available.height - 32)))
    let dialog = CenteredPanel(
      contentRect: NSRect(origin: .zero, size: contentSize),
      styleMask: [.titled, .closable], backing: .buffered, defer: false)
    dialog.title = title
    dialog.identifier = NSUserInterfaceItemIdentifier("superqode.dialog." + UUID().uuidString)
    dialog.isReleasedWhenClosed = false
    dialog.isFloatingPanel = false
    dialog.hidesOnDeactivate = false
    dialog.appearance = parent.effectiveAppearance
    dialog.animationBehavior = .alertPanel
    dialog.delegate = self
    dialog.contentView = hosting
    panel = dialog
    parent.addChildWindow(dialog, ordered: .above)
    dialog.setFrame(
      Self.centeredFrame(size: dialog.frame.size, visibleFrame: screen.visibleFrame), display: false
    )
    // Order first: beginModalSession otherwise applies AppKit's own placement.
    dialog.makeKeyAndOrderFront(nil)
    session = NSApp.beginModalSession(for: dialog)
    dialog.setFrame(
      Self.centeredFrame(size: dialog.frame.size, visibleFrame: screen.visibleFrame), display: true)
    let pump = Timer(timeInterval: 0.02, repeats: true) { [weak self] _ in
      // Registered only on RunLoop.main; no asynchronous modal-stack mutation.
      MainActor.assumeIsolated {
        guard let self, let session = self.session, let panel = self.panel,
          NSApp.modalWindow === panel
        else { return }
        if NSApp.runModalSession(session) != .continue {
          self.close()
        } else if self.firstModalPass {
          // The first modal-loop pass can apply AppKit's initial placement after
          // beginModalSession returns. Reconcile it after that pass as well.
          self.firstModalPass = false
          self.schedulePosition(force: true)
        }
      }
    }
    timer = pump
    RunLoop.main.add(pump, forMode: .common)
  }
  func windowDidResize(_ notification: Notification) {
    position()
  }
  func windowDidChangeScreen(_ notification: Notification) {
    schedulePosition(force: true)
  }
  private func schedulePosition(force: Bool = false) {
    DispatchQueue.main.async { [weak self] in
      guard let self, let panel = self.panel else { return }
      panel.contentView?.layoutSubtreeIfNeeded()
      self.position(force: force)
    }
  }
  private func position(force: Bool = false) {
    guard !positioning, let panel,
      let screen = parentWindow?.screen ?? presentationScreen
    else { return }
    // Content refreshes without a size/display change must not undo a user's
    // deliberate window drag. Initial modal placement is reconciled explicitly.
    guard
      force || positionedSize != panel.frame.size
        || positionedDisplay != screen.visibleFrame
    else { return }
    positionedSize = panel.frame.size
    positionedDisplay = screen.visibleFrame
    let frame = Self.centeredFrame(size: panel.frame.size, visibleFrame: screen.visibleFrame)
    guard
      abs(panel.frame.midX - frame.midX) > 0.5
        || abs(panel.frame.midY - frame.midY) > 0.5
    else { return }
    positioning = true
    defer { positioning = false }
    panel.setFrame(frame, display: true)
  }
  func windowShouldClose(_ sender: NSWindow) -> Bool {
    close()
    return false
  }
  func windowWillClose(_ notification: Notification) { close() }
  func close() {
    guard !closing else { return }
    closing = true
    defer { closing = false }
    // Close nested dialogs first so AppKit's modal-session stack unwinds in order.
    if let panel, let active = NSApp.modalWindow, active !== panel,
      active.identifier?.rawValue.hasPrefix("superqode.dialog.") == true,
      Self.isDescendant(active, of: panel)
    {
      active.performClose(nil)
    }
    timer?.invalidate()
    timer = nil
    if let session {
      NSApp.endModalSession(session)
      self.session = nil
    }
    let old = panel
    panel = nil
    if binding?.wrappedValue == true { binding?.wrappedValue = false }
    if let old { old.parent?.removeChildWindow(old) }
    old?.close()
    old?.contentView = nil
    parentWindow = nil
    presentationScreen = nil
    positionedSize = nil
    positionedDisplay = nil
  }
  private static func isDescendant(_ window: NSWindow, of ancestor: NSWindow) -> Bool {
    var parent = window.parent
    while let current = parent {
      if current === ancestor { return true }
      parent = current.parent
    }
    return false
  }
}
