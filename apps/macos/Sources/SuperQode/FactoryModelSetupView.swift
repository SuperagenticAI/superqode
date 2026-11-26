import SwiftUI

struct FactoryModelSetupView: View {
  @EnvironmentObject private var app: Workspace
  @ObservedObject var studio: FactoryStudioLibrary
  @ObservedObject var models: FactoryModelSetupLibrary
  var idle: Bool
  var executionOnly = false
  @State private var pendingDialog = ""
  @State private var cloudReviewProject = ""
  @State private var cloudReviewVersion = 0
  @State private var executionBinding = ""
  @State private var executionReference = ""
  @State private var executionProject = ""
  @State private var executionVersion = 0

  private var connected: Bool { !app.provider.isEmpty && app.provider != "acp" && !app.model.isEmpty }
  private var privacyBlocked: Bool {
    ([models.drafting] + models.execution).contains { string($0, "state") == "privacy-blocked" }
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      Label(executionOnly ? "Models that run this Factory" : "Connect models to your Factory", systemImage: "cpu")
        .font(.headline)
      ViewThatFits(in: .horizontal) {
        HStack { connectionButtons }
        VStack(alignment: .leading) { connectionButtons }
      }.disabled(!idle)
      if !executionOnly {
        Text("The drafting model helps design your Factory. Harness bindings choose the models that run its stages.")
          .font(.caption).foregroundStyle(.secondary)
        VStack(alignment: .leading, spacing: 8) {
          Text("1 · Draft the Factory").font(.subheadline.bold())
          Text(models.draftingReference.isEmpty ? "Starter generation · no model call" : models.draftingReference)
            .font(.callout).textSelection(.enabled)
          ViewThatFits(in: .horizontal) {
            HStack { draftingButtons }
            VStack(alignment: .leading) { draftingButtons }
          }
          if !models.drafting.isEmpty { status(models.drafting) }
        }
        Divider()
      }
      Text(executionOnly ? "Execution bindings" : "2 · Run the stages").font(.subheadline.bold())
      Text("Each binding keeps its own execution model. Selecting a drafting model leaves these bindings unchanged.")
        .font(.caption).foregroundStyle(.secondary)
      ForEach(Array(models.execution.enumerated()), id: \.offset) { _, row in
        VStack(alignment: .leading, spacing: 4) {
          Text("\(string(row, "binding"))\(row["fallback"] as? Bool == true ? " · fallback" : "") · \(string(row, "reference", "Choose a model"))")
            .font(.callout).textSelection(.enabled)
          status(row)
          if connected, row["fallback"] as? Bool != true {
            Button("Use connected model for this execution binding…") {
              executionBinding = string(row, "binding"); executionReference = app.provider + "/" + app.model
              executionProject = studio.project; executionVersion = studio.version
              pendingDialog = "execution"
            }.disabled(!idle)
          }
        }
      }
      if !string(models.report, "execution_error").isEmpty {
        Text(string(models.report, "execution_error")).font(.caption).foregroundStyle(.orange)
      } else if models.execution.isEmpty {
        Text("Check the draft to see its execution bindings. Choose a workflow starter first if your draft is empty.")
          .font(.caption).foregroundStyle(.secondary)
      }
      HStack {
        Button(models.checking ? "Checking…" : "Check models") {
          Task { await models.inspect(engine: app.engine, yaml: studio.text, checkConnections: true) }
        }.disabled(!idle || models.checking)
          .accessibilityIdentifier("factory.models.check")
        if !executionOnly {
          Button("Edit execution models") { studio.navigation.select("Configuration") }
            .disabled(!idle)
        }
      }
      Button("Try execution with one small trial") { studio.navigation.select("Runs") }
        .disabled(!idle)
      Text("Review and save changed bindings first. The trial asks before calling models, exercises real coding tools and retains usage evidence. Reported cost may remain unknown until the provider supplies it.")
        .font(.caption).foregroundStyle(.secondary)
      if privacyBlocked {
        Button("Review cloud permission…") {
          cloudReviewProject = studio.project; cloudReviewVersion = studio.version
          pendingDialog = "cloud"
        }
          .disabled(!idle || studio.text.isEmpty)
          .accessibilityIdentifier("factory.models.cloudPermission")
      }
      if !models.failure.isEmpty { Text(models.failure).font(.caption).foregroundStyle(.orange) }
      Text("Connection checks send no inference prompts. Generate a proposal to test drafting, then run a small reviewed trial to verify execution. Model calls may incur usage charges.")
        .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
    }
    .padding(14).brandSurface()
    .accessibilityElement(children: .contain)
    .accessibilityIdentifier(executionOnly ? "factory.models.execution" : "factory.models.setup")
    .task(id: studio.project + "\n" + models.draftingReference) {
      guard models.project == studio.project, models.report.isEmpty else { return }
      await models.inspect(engine: app.engine, yaml: studio.text)
    }
    .onChange(of: studio.project) { _, _ in pendingDialog = ""; executionBinding = "" }
    .onChange(of: studio.text) { _, _ in pendingDialog = ""; executionBinding = "" }
    .factoryConfirmation(
      isPresented: Binding(get: { !pendingDialog.isEmpty }, set: { if !$0 { pendingDialog = "" } }),
      title: pendingDialog == "cloud" ? "Allow cloud models in this Factory draft?" : "Change this draft's execution model?",
      message: pendingDialog == "cloud"
        ? "This permits cloud models for drafting and execution under the best route. Future confirmed model calls may send your description, draft and task context to the selected provider. Review the definition before saving; existing runs keep their pinned policy."
        : "Set binding \(executionBinding) to \(executionReference) in the editor. Other bindings, the drafting model and cloud permissions stay as configured. Review and save before running. Confirmed cloud trials may transmit task context and incur provider charges.",
      kind: pendingDialog == "cloud" ? .caution : .draft,
      badges: pendingDialog == "cloud"
        ? [FactoryConfirmBadge(label: "Route: best", symbol: "cloud", color: Brand.orange)]
        : [FactoryConfirmBadge(label: executionBinding.isEmpty ? "Binding" : executionBinding, symbol: "cpu", color: Brand.purple)],
      confirmTitle: pendingDialog == "cloud" ? "Set draft route to best" : "Use " + executionReference,
      onCancel: { pendingDialog = ""; executionBinding = "" },
      onConfirm: {
        let mode = pendingDialog
        pendingDialog = ""
        if mode == "cloud" {
          let identity = cloudReviewProject; let source = cloudReviewVersion
          Task {
            guard idle, studio.project == identity, studio.version == source else { return }
            await studio.edit(engine: app.engine, controls: ["default_route": "best"])
            await models.inspect(engine: app.engine, yaml: studio.text)
          }
        } else if mode == "execution" {
          let binding = executionBinding; let reference = executionReference
          executionBinding = ""
          guard !binding.isEmpty, idle, studio.project == executionProject, studio.version == executionVersion else { return }
          let identity = studio.project; let source = studio.version
          Task {
            guard studio.project == identity, studio.version == source else { return }
            await studio.edit(engine: app.engine, controls: ["binding": binding, "model": reference])
            await models.inspect(engine: app.engine, yaml: studio.text)
          }
        }
      }
    )
  }

  @ViewBuilder private var connectionButtons: some View {
    Button { app.openConnections("source:local", returningTo: "Factory Studio") } label: {
      Label("Connect local model…", systemImage: "desktopcomputer")
    }.accessibilityIdentifier("factory.models.connectLocal")
    Button { app.openConnections("source:key", returningTo: "Factory Studio") } label: {
      Label("Connect frontier model…", systemImage: "key")
    }.accessibilityIdentifier("factory.models.connectFrontier")
  }

  @ViewBuilder private var draftingButtons: some View {
    Button("Continue without a model") { models.draftingReference = "" }
      .disabled(!idle || models.draftingReference.isEmpty)
      .accessibilityIdentifier("factory.models.noModel")
    if connected {
      Button("Use connected model for drafting") {
        models.useConnected(provider: app.provider, model: app.model, harness: app.harness)
      }.disabled(!idle)
        .help("Use \(app.provider)/\(app.model) to design the Factory")
        .accessibilityIdentifier("factory.models.useConnected")
      Text("Connected: \(app.provider)/\(app.model)").font(.caption).foregroundStyle(.secondary)
    }
  }

  private func status(_ row: [String: Any]) -> some View {
    Text(string(row, "message"))
      .font(.caption)
      .foregroundStyle(row["eligible"] as? Bool == false ? Color.orange : Color.secondary)
      .fixedSize(horizontal: false, vertical: true)
  }
}
