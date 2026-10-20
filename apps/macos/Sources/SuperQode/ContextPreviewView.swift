import SwiftUI

struct ContextPreviewView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss var dismiss
  @State private var context: [String: Any] = [:]
  @State private var failure = ""
  @State private var instructions = ""
  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      HStack {
        Text("Next message context").font(.title2.weight(.semibold))
        Spacer()
        nativeButton("dialog.done", action: { dismiss() }, title: "Done") { Text("Done") }
      }
      Text(
        "Review the prompt and explicit project attachments. Your selected agent or harness adds its own instructions, history and tools during execution. Files are read again when you send."
      ).font(.callout).foregroundStyle(.secondary)
      if !failure.isEmpty { Text(failure).foregroundStyle(.orange) }
      HStack {
        Pill(title: "\((context["files"] as? [Any] ?? []).count) FILES")
        Pill(title: "\(context["image_count"] ?? 0) IMAGES")
        Text(app.harness).font(.caption.monospaced())
      }
      if !app.isManaged && app.interactionMode == "code" {
        HStack {
          TextField("Context tokens · blank for automatic", text: $app.contextWindow)
            .textFieldStyle(.roundedBorder).frame(width: 280)
          Toggle("Enable context summarization", isOn: $app.summarizeContext)
        }.font(.caption)
        DisclosureGroup("Compact this conversation now") {
          HStack {
            TextField("Optional summary instructions", text: $instructions).textFieldStyle(
              .roundedBorder)
            Button("Compact…") {
              guard
                app.confirm(
                  "Compact earlier model context?",
                  "Summarize earlier turns using this conversation’s provider and model. This may incur provider charges. The full transcript is preserved, and active project work must finish first.",
                  button: "Compact context")
              else { return }
              app.start(
                "context.compact",
                extra: ["source_job": app.selectedJob, "instructions": instructions])
              dismiss()
            }.disabled(!app.canContinue || app.anyActive)
          }
        }.font(.caption)
      }
      CodeBlock(text: string(context, "prompt", "Preparing preview…"))
      if !(context["harness"] as? [String: Any] ?? [:]).isEmpty {
        DisclosureGroup("Harness instructions, context policy and tool configuration") {
          CodeBlock(text: pretty(context["harness"])).frame(height: 220)
        }.font(.caption)
      }
    }.padding(24).frame(width: 800, height: 650).background { BrandBackdrop() }.task {
      do {
        context =
          try await app.engine.call(
            "context.preview",
            [
              "project": app.projectID, "prompt": app.draft, "harness": app.harness,
              "interaction_mode": app.interactionMode,
              "context_files": app.contextFiles,
              "image_ids": app.imageAttachments.map { string($0, "id") },
            ]) as? [String: Any] ?? [:]
      } catch { failure = error.localizedDescription }
    }
  }
}
