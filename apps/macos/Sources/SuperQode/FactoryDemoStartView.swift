import SwiftUI
import AppKit

/// A new sample directory only. Creation never calls a model or starts a worker.
struct FactoryDemoStartView: View {
  @EnvironmentObject private var app: Workspace
  @State private var creating = false
  @State private var createdPath = ""
  @State private var failure = ""

  var body: some View {
    VStack(alignment: .leading, spacing: 6) {
      Button(creating ? "Creating sample…" : "Try a disposable Factory sample…") {
        let panel = NSSavePanel()
        panel.title = "Create a disposable Factory sample"
        panel.nameFieldStringValue = "SuperQode First Run"
        panel.prompt = "Create sample"
        panel.canCreateDirectories = true
        panel.message = "Choose a new folder. SuperQode creates a tiny faulty app, a Factory and protected checks. No model calls, downloads or worker execution."
        guard panel.runModal() == .OK, let url = panel.url else { return }
        let project = app.projectID; let section = app.section; let welcome = app.showWelcome
        creating = true; failure = ""
        Task {
          defer { creating = false }
          do {
            let value = try await app.engine.call("factory.demo.create", ["destination": url.path, "confirmed": true]) as? [String: Any] ?? [:]
            createdPath = string(value, "project")
            guard !createdPath.isEmpty else { throw EngineError(message: "The sample directory was not returned.") }
            if app.projectID == project, app.section == section, app.showWelcome == welcome {
              try await app.open(createdPath, landing: .factory)
            }
          } catch { failure = error.localizedDescription }
        }
      }.disabled(creating || !app.connected || app.openingProject)
        .accessibilityIdentifier("factory.demo.create")
      Text("Reproduce a defect, choose a model, then repair and verify through the normal trial flow. Your own repository stays separate.")
        .font(.caption).foregroundStyle(.secondary)
      if !createdPath.isEmpty {
        Button("Open created sample") { app.openProjectInFactory(createdPath) }
          .disabled(app.openingProject || creating)
      }
      if !failure.isEmpty { Text(failure).font(.caption).foregroundStyle(.orange) }
    }
  }
}
