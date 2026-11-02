import SwiftUI

struct ExecutionRecoveryView: View {
  @EnvironmentObject var app: Workspace
  var body: some View {
    if !string(app.executionRecovery, "message").isEmpty {
      VStack(alignment: .leading, spacing: 10) {
        HStack(alignment: .top) {
          Label(app.executionRecovery["blocked"] as? Bool == true ? "Previous worker is still stopping" : "Interrupted work is available",
            systemImage: "arrow.counterclockwise.circle").font(.headline)
          Spacer()
          if app.executionRecovery["blocked"] as? Bool != true {
            Button("Dismiss") {
              let project = app.projectID
              app.perform {
                _ = try await app.engine.call("execution.recovery.acknowledge", ["project": project])
                await app.refreshJobs()
              }
            }
          }
        }
        Text(string(app.executionRecovery, "message")).font(.callout).foregroundStyle(.secondary)
        ForEach(app.executionRecovery["interrupted"] as? [[String: Any]] ?? [], id: \.projectRowID) { row in
          Button("Review · " + string(row, "title", "Interrupted run")) {
            app.selectJob(string(row, "id"), targetSection: "Workspace")
          }
        }
      }.padding(16).brandSurface().padding(.horizontal, 20).padding(.bottom, 12)
    }
  }
}
