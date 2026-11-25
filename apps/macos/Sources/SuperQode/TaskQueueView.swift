import SwiftUI

struct TaskQueueView: View {
  var compact = false
  @EnvironmentObject var app: Workspace
  @DialogDismiss var dismiss
  private var items: [[String: Any]] { app.taskQueue["items"] as? [[String: Any]] ?? [] }
  var body: some View {
    VStack(alignment: .leading, spacing: 18) {
      HStack {
        Text("Project task queue").font(.title2.weight(.semibold))
        Spacer()
        if !compact { nativeButton("dialog.done", action: { dismiss() }, title: "Done") { Text("Done") } }
      }
      Text(
        "Tasks keep their selected connection and run independently in order. Attached files are read when each task starts. A failed or stopped run pauses the queue; restarting the app never resumes it automatically."
      )
      .font(.callout).foregroundStyle(.secondary)
      HStack {
        Button("Start queue") {
          if app.confirm(
            "Run this project’s queue?",
            "Queued tasks use their saved connections, permissions and providers, and can incur provider charges. Tasks run one at a time. Pause prevents the next task from starting; Stop run cancels the active task.",
            button: "Start queue")
          {
            app.queueAction("queue.run")
          }
        }.buttonStyle(BrandButtonStyle()).disabled(
          items.allSatisfy { string($0, "state") != "pending" })
        Button("Pause queue") { app.queueAction("queue.pause") }
          .disabled(app.taskQueue["running"] as? Bool != true)
        Spacer()
        let queueRunning = app.taskQueue["running"] as? Bool == true
        FactoryStatusBadge(status: queueRunning ? .running : .pending, detail: queueRunning ? "Active" : "Paused")
      }
      ScrollView {
        LazyVStack(alignment: .leading, spacing: 12) {
          ForEach(items, id: \.projectRowID) { item in
            let request = item["request"] as? [String: Any] ?? [:]
            let state = string(item, "state")
            let status = FactoryStatus(raw: state)
            HStack(spacing: 0) {
              RoundedRectangle(cornerRadius: 2, style: .continuous)
                .fill(status.color.opacity(status.isActive ? 0.95 : 0.65))
                .frame(width: 3)
                .padding(.vertical, 8)
              VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .top, spacing: 8) {
                  Text(string(request, "prompt")).font(.system(size: 13, design: .monospaced))
                    .lineLimit(4)
                  Spacer()
                  FactoryStatusBadge(status: status)
                }
                if status == .running {
                  ThinkingBar().frame(maxWidth: 180)
                }
                Text(
                  string(request, "harness") + " · " + string(request, "provider") + " / "
                    + string(request, "model")
                )
                .font(.caption).foregroundStyle(.secondary)
                if !string(item, "error").isEmpty {
                  Text(string(item, "error")).font(.caption).foregroundStyle(Color(red: 0.86, green: 0.24, blue: 0.28))
                }
                HStack {
                  if !string(item, "job").isEmpty {
                    Button("Open run") {
                      app.selectJob(string(item, "job"))
                      app.section = "Workspace"
                      dismiss()
                    }
                  }
                  if state != "running" {
                    if state != "pending" {
                      Button("Retry") {
                        app.queueAction("queue.retry", extra: ["id": string(item, "id")])
                      }
                    }
                    Button {
                      app.queueAction(
                        "queue.move", extra: ["id": string(item, "id"), "direction": "up"])
                    } label: {
                      Image(systemName: "arrow.up")
                    }
                    Button {
                      app.queueAction(
                        "queue.move", extra: ["id": string(item, "id"), "direction": "down"])
                    } label: {
                      Image(systemName: "arrow.down")
                    }
                    Button("Remove", role: .destructive) {
                      app.queueAction("queue.remove", extra: ["id": string(item, "id")])
                    }
                  }
                }.controlSize(.small)
              }.padding(14)
            }
            .brandSurface(radius: 12)
            .overlay(
              RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(status.isActive || status == .failed ? status.color.opacity(0.36) : Color.clear, lineWidth: 1)
                .allowsHitTesting(false)
            )
          }
          if items.isEmpty {
            Text("Use Add to queue in the coding composer to prepare tasks.").foregroundStyle(
              .secondary
            ).padding()
          }
        }
      }.defaultScrollAnchor(.top)
    }.padding(compact ? 10 : 24).frame(width: compact ? nil : 740, height: compact ? nil : 600).background { BrandBackdrop() }
  }
}
