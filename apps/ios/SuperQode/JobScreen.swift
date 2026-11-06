import SwiftUI

struct JobScreen: View {
  let identity: String
  @EnvironmentObject private var store: CompanionStore
  @Environment(\.scenePhase) private var scenePhase
  @State private var detail: [String: JSONValue] = [:]
  @State private var events: [RemoteRecord] = []
  @State private var earlier: [RemoteRecord] = []
  @State private var historyCursor = ""
  @State private var eventCursor: Double = 0
  @State private var issue = ""
  @State private var loading = false
  @State private var acting = false
  @State private var continueThread = false
  @State private var steering = ""
  @State private var steerKey = UUID().uuidString
  @State private var confirmApproval = false
  @State private var approvalSnapshot: [String: JSONValue] = [:]
  @State private var confirmStop = false
  private var job: RemoteRecord { RemoteRecord(raw: detail) }
  private var pending: [String: JSONValue] { detail.object("pending_approval") }
  private var assistantText: String {
    events.compactMap { event -> String? in
      let data = event.raw.object("data")
      if event.text("type") == "answer" { return data.text("text") }
      if event.text("type") == "harness_event", ["delta", "model_delta", "message.delta"].contains(data.text("event")) {
        let payload = data.object("payload")
        return payload.text("text", payload.text("content"))
      }
      return nil
    }.joined()
  }

  var body: some View {
    ScrollView {
      LazyVStack(alignment: .leading, spacing: 18) {
        ConnectionStatus()
        if !issue.isEmpty { Label(issue, systemImage: "exclamationmark.triangle").font(.subheadline).foregroundStyle(.orange) }
        CompanionCard {
          HStack {
            HarnessBadge(name: detail.object("request").text("harness", "Run"))
            Spacer()
            Text(job.text("status").replacingOccurrences(of: "_", with: " ").capitalized)
              .font(.caption).foregroundStyle(job.text("status") == "needs_approval" ? Color.orange : Color.secondary)
          }
          let request = detail.object("request")
          Text(request.text("model", "Agent-managed model")).font(.caption).foregroundStyle(.secondary)
          if !detail.object("remote_origin").isEmpty { Label("Requested from \(detail.object("remote_origin").text("name"))", systemImage: "iphone").font(.caption) }
        }
        if !historyCursor.isEmpty { Button("Load earlier turns") { Task { await loadHistory(before: historyCursor) } } }
        ForEach(earlier) { turn in
          CompanionCard {
            Label("You", systemImage: "person.crop.circle").font(.caption).foregroundStyle(.secondary)
            Text(turn.text("prompt")).textSelection(.enabled)
            Divider()
            AssistantText(text: turn.text("response"))
          }
        }
        if !detail.object("request").text("prompt").isEmpty {
          CompanionCard {
            Label("You", systemImage: "person.crop.circle").font(.caption).foregroundStyle(.secondary)
            Text(detail.object("request").text("prompt")).textSelection(.enabled)
          }
        }
        if !assistantText.isEmpty {
          CompanionCard {
            Label("Agent", systemImage: "sparkles").font(.caption).foregroundStyle(CompanionTheme.accent)
            AssistantText(text: assistantText)
          }
        }
        if !pending.isEmpty {
          approvalCard
        } else if job.text("status") == "needs_approval" {
          Label("Loading the exact approval request…", systemImage: "hourglass").foregroundStyle(.orange)
        }
        if !detail.object("result").isEmpty, job.text("kind") != "task" {
          EvaluationResultCard(result: detail.object("result"))
        }
        if job.active, store.permissions.contains("steer"), detail.object("control_capabilities").flag("steer") {
          CompanionCard {
            Text("Guide the active run").font(.headline)
            TextField("Add direction without restarting", text: $steering, axis: .vertical).lineLimit(2...5)
            Button("Send guidance") { Task {
              if await act("jobs.steer", ["id": .string(identity), "text": .string(steering)], key: steerKey) {
                steering = ""; steerKey = UUID().uuidString
              }
            } }.disabled(acting || !store.reachable || steering.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
          }
        }
        if !events.isEmpty {
          DisclosureGroup("Run activity and details") {
            LazyVStack(alignment: .leading, spacing: 10) {
              ForEach(events.filter { event in
                event.text("type") != "answer" && !(event.text("type") == "harness_event" && ["delta", "model_delta", "message.delta"].contains(event.raw.object("data").text("event")))
              }) { event in
                VStack(alignment: .leading, spacing: 4) {
                  Text(event.text("type").replacingOccurrences(of: "_", with: " ").capitalized).font(.caption.bold())
                  let data = event.raw.object("data")
                  if !data.text("message").isEmpty { Text(data.text("message")).font(.caption).foregroundStyle(.secondary) }
                  JSONDetails(title: "Details", value: .object(data))
                }.padding(.vertical, 4)
              }
            }
          }.font(.subheadline)
        }
        if !job.active, job.text("kind") == "task", store.permissions.contains("tasks") {
          Button { continueThread = true } label: { Label("Continue conversation", systemImage: "arrow.turn.down.right") }
            .buttonStyle(.borderedProminent).foregroundStyle(.black)
        }
        if job.active, store.permissions.contains("cancel") {
          Button("Stop run", role: .destructive) { confirmStop = true }.disabled(acting || !store.reachable)
        }
      }.padding(20)
    }.background(CompanionTheme.background)
      .navigationTitle(job.text("conversation_title", job.text("title", "Run")))
      .navigationBarTitleDisplayMode(.inline)
      .refreshable { await load() }
      .task(id: scenePhase) {
        guard scenePhase == .active else { return }
        await load()
        if job.text("kind") == "task", earlier.isEmpty { await loadHistory() }
        while !Task.isCancelled {
          do { try await Task.sleep(for: .seconds(job.active ? 2 : 8)) } catch { break }
          await load()
        }
      }
      .sheet(isPresented: $continueThread) { NavigationStack { ComposeTaskScreen(project: job.text("project"), parent: identity) } }
      .confirmationDialog("Approve this exact action on your Mac?", isPresented: $confirmApproval, titleVisibility: .visible) {
        Button("Approve once") {
          let request = approvalSnapshot.text("request_id")
          Task { _ = await act("jobs.approve", ["id": .string(identity), "request_id": .string(request), "allow": .bool(true)], key: "approve:\(identity):\(request)") }
        }
      } message: { Text("Approve \(approvalSnapshot.object("tool").text("tool", approvalSnapshot.object("tool").text("name", "this action"))) once. If the pending request changed, the Mac will reject this decision.") }
      .confirmationDialog("Stop this run?", isPresented: $confirmStop, titleVisibility: .visible) {
        Button("Stop run", role: .destructive) { Task { _ = await act("jobs.cancel", ["id": .string(identity)], key: "cancel:\(identity)") } }
      } message: { Text("Stopping cannot undo edits or commands already completed on the Mac.") }
  }

  private var approvalCard: some View {
    let snapshot = pending
    return CompanionCard {
      Label("Your approval is needed", systemImage: "hand.raised.fill").font(.headline).foregroundStyle(.orange)
      let tool = snapshot.object("tool")
      Text(tool.text("tool", tool.text("name", "Agent action"))).font(.headline)
      let arguments = tool.object("arguments").isEmpty ? tool.object("args") : tool.object("arguments")
      if !arguments.text("command").isEmpty { Text(arguments.text("command")).font(.system(.caption, design: .monospaced)).textSelection(.enabled) }
      if !arguments.text("path").isEmpty { Text(arguments.text("path")).font(.caption).textSelection(.enabled) }
      JSONDetails(title: "Action details", value: .object(tool))
      HStack {
        Button("Approve once") { approvalSnapshot = snapshot; confirmApproval = true }.buttonStyle(.borderedProminent).foregroundStyle(.black)
        Button("Deny", role: .destructive) {
          let request = snapshot.text("request_id")
          Task { _ = await act("jobs.approve", ["id": .string(identity), "request_id": .string(request), "allow": .bool(false)], key: "deny:\(identity):\(request)") }
        }
      }.disabled(acting || !store.reachable || !store.permissions.contains("approve"))
    }
  }

  private func load() async {
    guard let api = store.api, !loading else { return }
    loading = true
    defer { loading = false }
    do {
      // Catch up in bounded pages; never discard unseen events or replay a mutation.
      for _ in 0..<4 {
        let page = try await api.rpc("jobs.get", ["id": .string(identity), "after": .number(eventCursor)]).object
        let next = page.records("events")
        if !next.isEmpty { events.append(contentsOf: next) }
        eventCursor = page.number("next_sequence")
        detail = page
        if !page.flag("has_more_events") { break }
      }
      issue = ""
    } catch is CancellationError { }
    catch { issue = error.localizedDescription }
  }
  private func loadHistory(before: String? = nil) async {
    guard let api = store.api else { return }
    do {
      var params: [String: JSONValue] = ["id": .string(identity)]
      if let before { params["before"] = .string(before) }
      let history = try await api.rpc("conversations.get", params).object
      earlier = history.records("turns") + earlier
      historyCursor = history.text("earlier")
    } catch is CancellationError { }
    catch { issue = error.localizedDescription }
  }
  private func act(_ method: String, _ params: [String: JSONValue], key: String) async -> Bool {
    guard let api = store.api, !acting else { return false }
    acting = true; issue = ""
    defer { acting = false }
    do {
      _ = try await api.rpc(method, params, key: key)
      await load()
      await store.refreshActivity()
      return true
    } catch { issue = error.localizedDescription; return false }
  }
}

struct AssistantText: View {
  let text: String
  var body: some View {
    let pieces = text.components(separatedBy: "```")
    VStack(alignment: .leading, spacing: 12) {
      ForEach(Array(pieces.enumerated()), id: \.offset) { index, part in
        if index % 2 == 1 {
          ScrollView(.horizontal) {
            Text(part).font(.system(.caption, design: .monospaced)).textSelection(.enabled).padding(12)
          }.background(.black.opacity(0.2), in: RoundedRectangle(cornerRadius: 12))
        } else if !part.isEmpty {
          Text(part).textSelection(.enabled).lineSpacing(4)
        }
      }
    }
  }
}

struct EvaluationResultCard: View {
  let result: [String: JSONValue]
  var body: some View {
    CompanionCard {
      Label("Evaluation evidence", systemImage: "chart.bar.xaxis").font(.headline)
      let gate = result.object("adoption_gate")
      if !gate.isEmpty {
        Label(gate.flag("accepted") ? "Acceptance checks passed" : "Candidate held for review", systemImage: gate.flag("accepted") ? "checkmark.seal.fill" : "hand.raised.fill")
          .foregroundStyle(gate.flag("accepted") ? CompanionTheme.accent : .orange)
      }
      if !result.text("summary").isEmpty { Text(result.text("summary")) }
      ForEach((result["variants"]?.array ?? []).enumerated().map { RemoteRecord(raw: $0.element.object.merging(["id": .string(String($0.offset))]) { old, _ in old }) }) { variant in
        VStack(alignment: .leading, spacing: 5) {
          Text(variant.text("name", variant.text("harness", "Variant"))).font(.subheadline.bold())
          Text("Passed \(Int(variant.raw.number("passed"))) · Failed \(Int(variant.raw.number("failed"))) · Skipped \(Int(variant.raw.number("skipped")))")
            .font(.caption).foregroundStyle(.secondary)
        }
      }
      JSONDetails(title: "Full evidence", value: .object(result))
      Text("Optimization candidates remain staged. Review and adoption happen on the Mac.").font(.caption).foregroundStyle(.secondary)
    }
  }
}

struct JSONDetails: View {
  let title: String
  let value: JSONValue
  @State private var expanded = false
  @State private var formatted = ""
  var body: some View {
    DisclosureGroup(isExpanded: $expanded) {
      if expanded {
        Text(formatted).font(.system(.caption2, design: .monospaced)).textSelection(.enabled)
      }
    } label: { Text(title).font(.caption) }
      .task(id: expanded ? value : .null) {
        guard expanded else { formatted = ""; return }
        let current = value
        let rendered = await Task.detached(priority: .utility) { current.pretty }.value
        guard !Task.isCancelled else { return }
        formatted = rendered
      }
  }
}
