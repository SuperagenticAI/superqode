import SwiftUI

struct TaskQueueView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss var dismiss
  private var items: [[String: Any]] { app.taskQueue["items"] as? [[String: Any]] ?? [] }
  var body: some View {
    VStack(alignment: .leading, spacing: 18) {
      HStack {
        Text("Project task queue").font(.title2.weight(.semibold))
        Spacer()
        nativeButton("dialog.done", action: { dismiss() }, title: "Done") { Text("Done") }
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
        Text(app.taskQueue["running"] as? Bool == true ? "RUNNING" : "PAUSED").font(
          .caption.monospaced())
      }
      ScrollView {
        LazyVStack(alignment: .leading, spacing: 12) {
          ForEach(items, id: \.projectRowID) { item in
            let request = item["request"] as? [String: Any] ?? [:]
            let state = string(item, "state")
            VStack(alignment: .leading, spacing: 8) {
              HStack {
                Text(string(request, "prompt")).font(.system(size: 13, design: .monospaced))
                  .lineLimit(4)
                Spacer()
                Pill(title: state, color: state == "failed" ? .orange : .qAccent)
              }
              Text(
                string(request, "harness") + " · " + string(request, "provider") + " / "
                  + string(request, "model")
              )
              .font(.caption).foregroundStyle(.secondary)
              if !string(item, "error").isEmpty {
                Text(string(item, "error")).font(.caption).foregroundStyle(.orange)
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
            }.padding(14).brandSurface(radius: 12)
          }
          if items.isEmpty {
            Text("Use Add to queue in the coding composer to prepare tasks.").foregroundStyle(
              .secondary
            ).padding()
          }
        }
      }.defaultScrollAnchor(.top)
    }.padding(24).frame(width: 740, height: 600).background { BrandBackdrop() }
  }
}
