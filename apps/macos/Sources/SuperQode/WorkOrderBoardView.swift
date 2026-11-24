import SwiftUI

struct WorkOrderBoardView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss var dismiss
  @State private var items: [[String: Any]] = []
  @State private var selected = ""
  @State private var failure = ""
  @State private var previousTaskStatuses: [String: String] = [:]
  private var order: [String: Any] {
    items.first { string($0, "work_order_id") == selected } ?? [:]
  }
  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      HStack {
        Text("WorkOrders").font(.title.weight(.semibold)).modifier(BrandText())
        Spacer()
        FactorySoundToggleButton()
        Text("Live on your Mac").font(.caption).foregroundStyle(.secondary)
        nativeButton("dialog.done", action: { dismiss() }, title: "Done") { Text("Done") }
      }
      if !failure.isEmpty { Text(failure).foregroundStyle(.orange) }
      HSplitView {
        ScrollView {
          LazyVStack(alignment: .leading, spacing: 10) {
            ForEach(items, id: \.workOrderID) { item in
              let itemStatus = FactoryStatus(raw: string(item, "status"))
              let isSelected = selected == item.workOrderID
              Button {
                selected = item.workOrderID
              } label: {
                HStack(spacing: 0) {
                  RoundedRectangle(cornerRadius: 2, style: .continuous)
                    .fill(itemStatus.color.opacity(isSelected ? 0.95 : 0.65))
                    .frame(width: 3)
                    .padding(.vertical, 6)
                  VStack(alignment: .leading, spacing: 7) {
                    Text(string(item, "goal")).font(.headline).lineLimit(3)
                    FactoryStatusBadge(status: itemStatus)
                  }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
                }
                .brandSurface(radius: 12)
                .overlay(
                  RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .strokeBorder(isSelected ? itemStatus.color.opacity(0.45) : Color.clear, lineWidth: 1.2)
                    .allowsHitTesting(false)
                )
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
              HStack(spacing: 8) {
                FactoryStatusBadge(raw: string(order, "status"))
                if !string(order, "harness").isEmpty {
                  Label(string(order, "harness"), systemImage: "cpu")
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(Color.primary.opacity(0.05), in: Capsule())
                }
              }
              Text("Tasks").font(.headline)
              ForEach(order["tasks"] as? [[String: Any]] ?? [], id: \.workTaskID) { task in
                let taskStatus = FactoryStatus(raw: string(task, "status"))
                HStack(spacing: 0) {
                  RoundedRectangle(cornerRadius: 2, style: .continuous)
                    .fill(taskStatus.color.opacity(taskStatus.isActive ? 0.95 : 0.7))
                    .frame(width: 3)
                    .padding(.vertical, 6)
                  HStack(alignment: .top, spacing: 10) {
                    if taskStatus.isPulsing {
                      FactoryStatusDot(status: taskStatus, size: 8)
                        .padding(.top, 2)
                    } else {
                      Image(systemName: taskStatus.symbol)
                        .foregroundStyle(taskStatus.color)
                        .padding(.top, 2)
                    }
                    VStack(alignment: .leading, spacing: 5) {
                      Text(string(task, "title")).font(.system(size: 13, weight: .semibold))
                      Text(string(task, "role") + " · " + string(task, "worker_id")).font(.caption)
                        .foregroundStyle(.secondary)
                      if taskStatus == .running {
                        ThinkingBar().frame(maxWidth: 180)
                      }
                      if !string(task, "error").isEmpty {
                        Text(string(task, "error")).font(.caption).foregroundStyle(Color(red: 0.86, green: 0.24, blue: 0.28))
                      }
                    }
                    Spacer()
                    FactoryStatusBadge(status: taskStatus)
                  }.padding(12)
                }
                .brandSurface(radius: 10)
                .overlay(
                  RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .strokeBorder(taskStatus.isActive || taskStatus == .failed ? taskStatus.color.opacity(0.35) : Color.clear, lineWidth: 1)
                    .allowsHitTesting(false)
                )
              }
              DisclosureGroup("Diagnostics & raw receipts") {
                VStack(alignment: .leading, spacing: 10) {
                  let usage = order["usage"] as? [String: Any] ?? [:]
                  DisclosureGroup("Usage and budget") {
                    CodeBlock(text: pretty(["usage": usage, "budget": order["budget"] ?? [:]])).frame(
                      height: 180)
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
                }.padding(.top, 6)
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
          let nextItems = result["items"] as? [[String: Any]] ?? []
          items = nextItems
          if selected.isEmpty { selected = items.first?.workOrderID ?? "" }
          let activeOrder = nextItems.first { $0.workOrderID == selected } ?? [:]
          let activeTasks = activeOrder["tasks"] as? [[String: Any]] ?? []
          if !previousTaskStatuses.isEmpty,
             let cue = FactorySoundEngine.cueForTaskTransitions(previous: previousTaskStatuses, current: activeTasks) {
            FactorySoundEngine.play(cue)
          }
          var updated: [String: String] = [:]
          for task in activeTasks {
            let id = task.workTaskID
            if !id.isEmpty { updated[id] = string(task, "status") }
          }
          previousTaskStatuses = updated
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
