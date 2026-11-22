import SwiftUI

struct FactoryCampaignView: View {
  @EnvironmentObject var app: Workspace
  @ObservedObject var studio: FactoryStudioLibrary
  var active: Bool
  @StateObject private var library = FactoryCampaignLibrary()
  @State private var kind = ""
  @State private var source = ""
  @State private var confirmation = ""
  private var manifest: [String: Any] { library.current["manifest"] as? [String: Any] ?? [:] }
  private var policy: [String: Any] { manifest["policy"] as? [String: Any] ?? [:] }
  private var state: [String: Any] { library.current["state"] as? [String: Any] ?? [:] }
  private var idle: Bool { !library.busy && !studio.busy && !app.anyActive && !app.busy }
  private var arguments: [String: Any] { ["id": library.selected, "digest": string(manifest, "digest")] }

  var body: some View {
    DisclosureGroup("Bounded automation (advanced)") {
      VStack(alignment: .leading, spacing: 10) {
        Text("Save an opted-in experiment policy in the Factory definition first. Campaigns verify event sources, reserve an aggregate budget and stop for uncertainty or human review. They never activate proposals.")
          .font(.caption).foregroundStyle(.secondary)
        FactoryActionRow {
          Button("Refresh campaigns") { Task { await library.perform(app.engine, "list") } }.disabled(!idle)
          Button("Prepare campaign from saved policy…") { confirmation = "create" }.disabled(!idle)
        }
        Picker("Campaign", selection: $library.selected) {
          Text("Choose a campaign").tag("")
          ForEach(library.campaigns.map { string($0["manifest"] as? [String: Any] ?? [:], "id") }, id: \.self) { identity in
            Text(String(identity.prefix(22))).tag(identity)
          }
        }
        if !manifest.isEmpty {
          Text("Status: " + string(state, "status") + " · reserved experiments: " + String(library.current["reserved_experiments"] as? Int ?? 0)).font(.caption)
          Picker("Trigger", selection: $kind) {
            Text("Choose a trigger").tag("")
            ForEach(policy["triggers"] as? [String] ?? [], id: \.self) { value in Text(value.replacingOccurrences(of: "_", with: " ")).tag(value) }
          }
          if kind == "reviewed_failure" { TextField("Reviewed failure ID", text: $source).textFieldStyle(.roundedBorder) }
          FactoryActionRow {
            Button("Review event source") {
              var params = arguments; params["kind"] = kind; params["source"] = source
              Task { await library.perform(app.engine, "event.preview", params) }
            }.disabled(!idle || kind.isEmpty || (kind == "reviewed_failure" && source.isEmpty))
            Button("Queue reviewed event…") { confirmation = "enqueue" }.disabled(!idle || library.preview.isEmpty)
          }
          if !library.preview.isEmpty { CodeBlock(text: pretty(library.preview)) }
          FactoryActionRow {
            Button("Run next bounded experiment…") { confirmation = "run" }.disabled(!idle || string(state, "status") != "ready")
            Button("Start bounded campaign worker…") { confirmation = "worker" }.disabled(!idle || string(state, "status") != "ready")
            Button("Stop after current action…") { confirmation = "stop" }.disabled(library.busy)
          }
          if studio.busy { Button("Cancel active Factory job") { Task { await studio.cancel(engine: app.engine) } } }
          DisclosureGroup("Campaign evidence & budget") { CodeBlock(text: pretty(library.current)) }
        }
        if !library.failure.isEmpty { Text(library.failure).foregroundStyle(.orange).textSelection(.enabled) }
      }.padding(.top, 8)
    }.font(.caption)
    .task(id: app.projectID + String(active)) {
      guard active else { return }; library.enter(app.projectID); await library.perform(app.engine, "list")
    }
    .onChange(of: library.selected) { _, _ in kind = ""; source = ""; library.clearPreview(); confirmation = "" }
    .onChange(of: kind) { _, _ in library.clearPreview() }
    .onChange(of: source) { _, _ in library.clearPreview() }
    .onChange(of: app.projectID) { _, _ in confirmation = ""; library.enter(app.projectID) }
    .onChange(of: active) { _, value in if !value { confirmation = "" } }
    .alert("Confirm bounded automation", isPresented: Binding(get: { !confirmation.isEmpty }, set: { if !$0 { confirmation = "" } })) {
      Button("Cancel", role: .cancel) { confirmation = "" }
      Button("Continue") { let action = confirmation; confirmation = ""; execute(action) }
    } message: {
      Text(["run", "worker"].contains(confirmation) ? "Enable bounded model execution for admitted events? The worker stops at the campaign deadline, hold or review boundary. No adoption or release is authorized." : confirmation == "stop" ? "Stop admitting further experiments? The current action may finish within its budget; use Cancel active Factory job to interrupt it." : confirmation == "enqueue" ? "Queue this exact reviewed source and digest? Queuing makes no model calls." : "Pin the saved Factory's enabled policy and experiment budget? This does not start models.")
    }
  }
  private func execute(_ action: String) {
    let identity = app.projectID
    var params = arguments
    if action == "enqueue" {
      params["kind"] = library.preview["kind"]; params["key"] = library.preview["key"]
      params["source"] = library.preview["source"]; params["source_digest"] = library.preview["digest"]
    }
    Task {
      guard app.projectID == identity else { return }
      if ["run", "worker"].contains(action) {
        await studio.start(engine: app.engine, action: action == "worker" ? "campaign-worker" : "campaign-run", extra: ["campaign": params["id"] ?? "", "campaign_digest": params["digest"] ?? ""])
        guard app.projectID == identity else { return }; await library.perform(app.engine, "list"); await studio.refreshImprovements(engine: app.engine)
      } else { await library.perform(app.engine, action, params) }
    }
  }
}
