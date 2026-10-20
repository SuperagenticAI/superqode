import SwiftUI

struct WorkOrderBoardView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss var dismiss
  @State private var items: [[String: Any]] = []
  @State private var selected = ""
  @State private var failure = ""
  private var order: [String: Any] {
    items.first { string($0, "work_order_id") == selected } ?? [:]
  }
  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      HStack {
        Text("WorkOrders").font(.title.weight(.semibold)).modifier(BrandText())
        Spacer()
        Text("Live on your Mac").font(.caption).foregroundStyle(.secondary)
        nativeButton("dialog.done", action: { dismiss() }, title: "Done") { Text("Done") }
      }
      if !failure.isEmpty { Text(failure).foregroundStyle(.orange) }
      HSplitView {
        ScrollView {
          LazyVStack(alignment: .leading, spacing: 10) {
            ForEach(items, id: \.workOrderID) { item in
              Button {
                selected = item.workOrderID
              } label: {
                VStack(alignment: .leading, spacing: 7) {
                  Text(string(item, "goal")).font(.headline).lineLimit(3)
                  Pill(title: string(item, "status"))
                }.padding(14).frame(maxWidth: .infinity, alignment: .leading).brandSurface()
              }.buttonStyle(.plain)
            }
          }
        }.frame(minWidth: 220, idealWidth: 290, maxWidth: 350)
        ScrollView {
          VStack(alignment: .leading, spacing: 18) {
            if order.isEmpty {
              EmptyState(
                icon: "square.stack.3d.up", title: "Work with a team of agents",
                detail:
                  "Create a WorkOrder in Tools, then track its tasks, worker leases, budgets, checks and reviews here."
              )
            } else {
              Text(string(order, "goal")).font(.title2.weight(.semibold))
              HStack {
                Pill(title: string(order, "status"))
                Text(string(order, "harness")).font(.caption.monospaced())
              }
              let usage = order["usage"] as? [String: Any] ?? [:]
              DisclosureGroup("Usage and budget") {
                CodeBlock(text: pretty(["usage": usage, "budget": order["budget"] ?? [:]])).frame(
                  height: 180)
              }
              Text("Tasks").font(.headline)
              ForEach(order["tasks"] as? [[String: Any]] ?? [], id: \.workTaskID) { task in
                HStack(alignment: .top) {
                  Image(
                    systemName: string(task, "status") == "completed"
                      ? "checkmark.circle.fill" : "circle.dotted"
                  ).foregroundStyle(Brand.gradient)
                  VStack(alignment: .leading, spacing: 5) {
                    Text(string(task, "title")).font(.system(size: 13, weight: .semibold))
                    Text(string(task, "role") + " · " + string(task, "worker_id")).font(.caption)
                      .foregroundStyle(.secondary)
                    if !string(task, "error").isEmpty {
                      Text(string(task, "error")).font(.caption).foregroundStyle(.orange)
                    }
                  }
                  Spacer()
                  Pill(title: string(task, "status"))
                }.padding(12).brandSurface(radius: 10)
              }
              DisclosureGroup("Worker leases and responsiveness") {
                CodeBlock(text: pretty(order["workers"])).frame(height: 160)
              }
              DisclosureGroup("Acceptance gates and reviews") {
                CodeBlock(text: pretty(order["gates"])).frame(height: 160)
              }
              DisclosureGroup("Latest events") {
                CodeBlock(text: pretty(order["events"])).frame(height: 200)
              }
            }
          }.padding(.leading, 16).frame(maxWidth: .infinity, alignment: .leading)
        }.defaultScrollAnchor(.top)
      }
    }.padding(24).frame(width: 1050, height: 740).background { BrandBackdrop() }.task {
      while !Task.isCancelled {
        do {
          let result =
            try await app.engine.call("workorders.snapshot", ["project": app.projectID])
            as? [String: Any] ?? [:]
          items = result["items"] as? [[String: Any]] ?? []
          if selected.isEmpty { selected = items.first?.workOrderID ?? "" }
          failure = ""
          try await Task.sleep(for: .seconds(2))
        } catch is CancellationError { return } catch {
          failure = error.localizedDescription
          try? await Task.sleep(for: .seconds(4))
        }
      }
    }
  }
}
extension Dictionary where Key == String, Value == Any {
  var workOrderID: String { string(self, "work_order_id") }
  var workTaskID: String { string(self, "task_id") }
}
