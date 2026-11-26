import SwiftUI

struct FactoryModelSetupView: View {
  @EnvironmentObject private var app: Workspace
  @ObservedObject var studio: FactoryStudioLibrary
  @ObservedObject var models: FactoryModelSetupLibrary
  var idle: Bool
  var executionOnly = false
  @State private var reviewCloud = false
  @State private var cloudReviewProject = ""
  @State private var cloudReviewVersion = 0

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
      if privacyBlocked {
        Button("Review cloud permission…") {
          cloudReviewProject = studio.project; cloudReviewVersion = studio.version
          reviewCloud = true
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
    .onChange(of: studio.project) { _, _ in reviewCloud = false }
    .onChange(of: studio.text) { _, _ in reviewCloud = false }
    .confirmationDialog("Allow cloud models in this Factory draft?", isPresented: $reviewCloud, titleVisibility: .visible) {
      Button("Set draft route to best") {
        Task {
          guard idle, studio.project == cloudReviewProject, studio.version == cloudReviewVersion else { return }
          await studio.edit(engine: app.engine, controls: ["default_route": "best"])
          await models.inspect(engine: app.engine, yaml: studio.text)
        }
      }
      Button("Keep current route", role: .cancel) {}
    } message: {
      Text("This permits cloud models for drafting and execution under the best route. Future confirmed model calls may send your description, draft and task context to the selected provider. Review the definition before saving; existing runs keep their pinned policy.")
    }
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
