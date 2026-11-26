import SwiftUI
import AppKit

struct FactoryRunSummaryView: View {
  @EnvironmentObject private var app: Workspace
  @ObservedObject var studio: FactoryStudioLibrary
  var inspectChecks: () -> Void = {}
  @State private var text = ""
  @State private var failure = ""
  private var identity: String {
    let order = studio.detail["work_order"] as? [String: Any] ?? [:]
    let artifacts = order["artifacts"] as? [[String: Any]] ?? []
    return studio.project + "\n" + studio.run + "\n" + string(order, "status") + "\n" + String(artifacts.count)
  }
  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      Label("Your trial, explained", systemImage: "doc.text.magnifyingglass").font(.headline)
      if !text.isEmpty {
        Text(text).font(.callout).textSelection(.enabled)
        Button("Copy result summary") {
          NSPasteboard.general.clearContents(); NSPasteboard.general.setString(text, forType: .string)
        }
      }
      if !failure.isEmpty { Text(failure).font(.caption).foregroundStyle(.orange) }
      HStack {
        Button("Inspect checks") { inspectChecks() }
        Button("Review execution models") { studio.navigation.select("Configuration") }
      }
      if studio.gettingStarted["demo"] as? Bool == true {
        Button("Try Factory on my repository…") { app.chooseProject(openFolder: app.openProjectInFactory) }
      }
    }.padding(14).brandSurface()
      .accessibilityIdentifier("factory.onboarding.result")
      .task(id: identity) {
        text = ""; failure = ""
        let project = studio.project; let run = studio.run; let token = identity
        guard !project.isEmpty, !run.isEmpty else { return }
        do {
          let value = try await app.engine.call("factory.onboarding.result", ["project": project, "run": run]) as? [String: Any] ?? [:]
          guard !Task.isCancelled, studio.project == project, studio.run == run, identity == token else { return }
          text = string(value, "text")
        } catch {
          if !Task.isCancelled, studio.project == project, studio.run == run, identity == token { failure = error.localizedDescription }
        }
      }
  }
}
