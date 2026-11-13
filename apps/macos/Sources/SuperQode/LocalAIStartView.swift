import SwiftUI

/// The one Local AI Start view used by every entry point: the sidebar Local AI
/// screen, the welcome screen, the start grid tile, the Connect sheet and the
/// harness-first path. Order: Apple on-device, Ollama and LM Studio, this Mac,
/// models, then a compact harness menu next to Start coding. Advanced tools live
/// on the separate Advanced tab.
struct LocalAIStartView: View {
  let project: String
  /// The Connect sheet uses a shorter header.
  var compact = false
  var active = true
  var dismissOnConnect = false
  /// A harness picked first in Connect is preset in the harness menu.
  var preferredHarness = ""
  var form: InstalledLocalDraft?
  var openProject: (() -> Void)?
  var openAdvanced: (() -> Void)?

  var body: some View {
    InstalledLocalModelPicker(
      project: project, dismissOnUse: dismissOnConnect, active: active,
      preferredHarness: preferredHarness, form: form, openProject: openProject,
      layout: .start, compact: compact, openAdvanced: openAdvanced
    )
    .id(project)
  }
}
