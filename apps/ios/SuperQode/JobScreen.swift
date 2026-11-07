import SwiftUI
import UIKit

private struct PendingSend: Identifiable, Equatable {
  let id: String
  let text: String
}

struct JobScreen: View {
  let identity: String
  @EnvironmentObject private var store: CompanionStore
  @Environment(\.scenePhase) private var scenePhase
  @State private var shownID: String
  @State private var reply = ""
  @State private var pending: [PendingSend] = []
  @State private var showNewThread = false
  @FocusState private var composing: Bool
  @State private var pendingHold = false
  @State private var connections: [RemoteRecord] = []
  @State private var nextConnection: RemoteRecord?
  @State private var detail: [String: JSONValue] = [:]
  init(identity: String) {
    self.identity = identity
    _shownID = State(initialValue: identity)
  }
  @State private var events: [RemoteRecord] = []
  @State private var earlier: [RemoteRecord] = []
  @State private var historyCursor = ""
  @State private var eventCursor: Double = 0
  @State private var issue = ""
  @State private var loadGeneration = 0
  @State private var acting = false
  @State private var steering = ""
  @State private var steerKey = UUID().uuidString
  @State private var confirmApproval = false
  @State private var approvalSnapshot: [String: JSONValue] = [:]
  @State private var confirmStop = false
  @State private var showComparison = false
  @State private var comparisonData: [String: JSONValue] = [:]
  private var job: RemoteRecord { RemoteRecord(raw: detail) }
  private var approvalRequest: [String: JSONValue] { detail.object("pending_approval") }
  private var failureMessage: String {
    guard job.text("status") == "failed" else { return "" }
    let result = detail.object("result")
    if !result.text("error").isEmpty { return String(result.text("error").prefix(4000)) }
    for event in events.reversed() {
      let data = event.raw.object("data")
      if event.text("type") == "error", !data.text("message").isEmpty { return String(data.text("message").prefix(4000)) }
      if event.text("type") == "harness_event", ["error", "failure", "failed"].contains(data.text("event")) {
        let message = data.object("payload").text("message", data.object("payload").text("text"))
        if !message.isEmpty { return String(message.prefix(4000)) }
      }
    }
    return "Open run activity for the recorded details, or inspect this run on your Mac."
  }
  private var showWorking: Bool {
    job.active || acting || (!pending.isEmpty && !pendingHold)
  }
  private var workingStatus: String {
    let status = job.text("status")
    if ["needs_approval", "cancelling", "running", "queued"].contains(status) { return status }
    return "running"
  }
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
        if acting { ProgressView("Sending…") }
        if !issue.isEmpty { Label(issue, systemImage: "exclamationmark.triangle").font(.subheadline).foregroundStyle(CompanionTheme.warning) }
        CompanionCard {
          HStack {
            HarnessBadge(name: detail.object("request").text("harness", "Run"))
            Spacer()
            Text(job.text("status").replacingOccurrences(of: "_", with: " ").capitalized)
              .font(.caption).foregroundStyle(job.text("status") == "needs_approval" ? CompanionTheme.warning : Color.secondary)
          }
          let request = detail.object("request")
          Text(request.text("model", "Agent-managed model")).font(.caption).foregroundStyle(.secondary)
          if !detail.object("remote_origin").isEmpty { Label("Requested from \(detail.object("remote_origin").text("name"))", systemImage: "iphone").font(.caption) }
        }
        if !failureMessage.isEmpty {
          CompanionCard {
            Label("The agent could not complete this run", systemImage: "exclamationmark.triangle").font(.headline).foregroundStyle(CompanionTheme.warning)
            Text(failureMessage).font(.subheadline).textSelection(.enabled)
            Text("Connection and provider setup is managed on your Mac. This run has not been restarted automatically.").font(.caption).foregroundStyle(.secondary)
          }
        }
        if !historyCursor.isEmpty { Button("Load earlier turns") { Task { await loadHistory(before: historyCursor) } } }
        ForEach(earlier) { turn in
          CompanionCard {
            Label("You", systemImage: "person.crop.circle").font(.caption).foregroundStyle(.secondary)
            Text(turn.text("prompt")).textSelection(.enabled)
            Divider()
            AssistantText(text: turn.text("response")).equatable()
          }
        }
        if !detail.object("request").text("prompt").isEmpty {
          CompanionCard {
            Label("You", systemImage: "person.crop.circle").font(.caption).foregroundStyle(.secondary)
            Text(detail.object("request").text("prompt")).textSelection(.enabled)
          }
        }
        if !approvalRequest.isEmpty {
          approvalCard
        } else if job.text("status") == "needs_approval" {
          Label("Loading the exact approval request…", systemImage: "hourglass").foregroundStyle(CompanionTheme.warning)
        }
        if !detail.text("project").isEmpty {
          CompanionCard {
            NavigationLink("Export recorded evidence") { RecordedEvidenceExportScreen(project: detail.text("project"), job: shownID) }
            if job.text("kind") == "task", !job.active { NavigationLink("Handoff to a new thread") { ThreadHandoffScreen(project: detail.text("project"), job: shownID) } }
          }
        }
        if !assistantText.isEmpty {
          CompanionCard {
            Label("Agent", systemImage: "sparkles").font(.caption).foregroundStyle(CompanionTheme.accent)
            AssistantText(text: assistantText).equatable()
          }
        }
        ForEach(pending) { item in
          CompanionCard {
            Label("You", systemImage: "person.crop.circle").font(.caption).foregroundStyle(.secondary)
            Text(item.text).textSelection(.enabled)
            Text(pendingHold && !issue.isEmpty ? issue : (job.active ? "Sends when this turn finishes" : "Sending…"))
              .font(.caption).foregroundStyle(.secondary)
          }
        }
        if !detail.object("result").isEmpty, ["evaluation", "optimization"].contains(job.text("kind")) {
          EvaluationResultCard(result: detail.object("result")) { comparison in
            comparisonData = comparison
            showComparison = true
          }
        } else if !detail.object("result").isEmpty && job.text("kind") != "task" {
          CompanionCard {
            Label("Recorded result", systemImage: "doc.text").font(.headline)
            if !detail.object("result").text("summary").isEmpty { Text(detail.object("result").text("summary")) }
            JSONDetails(title: "Result details", value: .object(detail.object("result")))
            Text("Specialized configuration and management for this workflow remain on your Mac.").font(.caption).foregroundStyle(.secondary)
          }
        }
        if job.active, store.permissions.contains("steer"), detail.object("control_capabilities").flag("steer") {
          CompanionCard {
            Text("Guide the active run").font(.headline)
            TextField("Add direction without restarting", text: $steering, axis: .vertical).lineLimit(2...5).disabled(acting)
              .onChange(of: steering) { _, _ in if !acting { steerKey = UUID().uuidString } }
            Button("Send guidance") {
              let text = steering
              let key = steerKey
              Task {
                if await act("jobs.steer", ["id": .string(shownID), "text": .string(text)], key: key) {
                  steering = ""; steerKey = UUID().uuidString
                }
              }
            }.disabled(acting || !store.canMutate || steering.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
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
        if !job.active, job.text("kind") == "task" {
          NavigationLink { ProjectReviewScreen(project: job.text("project"), job: shownID) } label: { Label("Review this turn", systemImage: "text.magnifyingglass") }
        }
        if job.active, store.permissions.contains("cancel") {
          Button("Stop run", role: .destructive) { confirmStop = true }.disabled(acting || !store.canMutate)
        }
      }.padding(20)
    }
    .scrollDismissesKeyboard(.interactively)
    .background(CompanionTheme.background)
      .safeAreaInset(edge: .bottom, spacing: 0) {
        VStack(spacing: 0) {
          if showWorking {
            CompanionWorkingCard(status: workingStatus)
              .padding(.horizontal, 12)
              .padding(.top, 8)
              .padding(.bottom, 4)
          }
          if job.text("kind") == "task" || detail.isEmpty { replyBar }
        }
      }
      .navigationTitle(job.text("conversation_title", job.text("title", "Run")))
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItemGroup(placement: .keyboard) {
          Spacer()
          Button("Hide") { composing = false }
        }
        ToolbarItem(placement: .primaryAction) {
          Button("New thread") { showNewThread = true }
            .disabled(job.text("project").isEmpty || !store.permissions.contains("tasks"))
        }
      }
      .refreshable { await load() }
      .task(id: "\(shownID)-\(scenePhase)") {
        guard scenePhase == .active else { return }
        events = []; eventCursor = 0; earlier = []; historyCursor = ""; detail = [:]
        await load()
        if job.text("kind") == "task" || detail.isEmpty, earlier.isEmpty { await loadHistory() }
        await loadConnections()
        while !Task.isCancelled {
          do { try await Task.sleep(for: .seconds(job.active || !pending.isEmpty ? 1 : 8)) } catch { break }
          await load()
        }
      }
      .navigationDestination(isPresented: $showComparison) { EvaluationComparisonScreen(comparison: comparisonData) }
      .confirmationDialog("Approve this exact action on your Mac?", isPresented: $confirmApproval, titleVisibility: .visible) {
        Button("Approve once") {
          let request = approvalSnapshot.text("request_id")
          Task { _ = await act("jobs.approve", ["id": .string(shownID), "request_id": .string(request), "allow": .bool(true)], key: "approve:\(shownID):\(request)") }
        }
      } message: { Text("Approve \(approvalSnapshot.object("tool").text("tool", approvalSnapshot.object("tool").text("name", "this action"))) once. If the pending request changed, the Mac will reject this decision.") }
      .confirmationDialog("Stop this run?", isPresented: $confirmStop, titleVisibility: .visible) {
        Button("Stop run", role: .destructive) { Task { _ = await act("jobs.cancel", ["id": .string(shownID)], key: "cancel:\(shownID)") } }
      } message: { Text("Stopping cannot undo edits or commands already completed on the Mac.") }
      .sheet(isPresented: $showNewThread) {
        NavigationStack { ComposeTaskScreen(project: job.text("project")) }
      }
  }

  private var replyBar: some View {
    VStack(alignment: .leading, spacing: 8) {
      Menu {
        if connections.isEmpty {
          Button("Open the Mac once so its harnesses can be listed") {}.disabled(true)
        }
        ForEach(HarnessChoiceGroup.sections(connections)) { section in
          Section(section.title) {
            ForEach(section.rows) { choice in
              Button(connectionLabel(choice)) { Task { await chooseHarness(choice) } }
            }
          }
        }
      } label: {
        HStack(spacing: 6) {
          if let current = nextConnection ?? selectedRequestConnection {
            HarnessMark(name: current.text("name"), iconKey: current.text("icon_key"), size: 16)
          }
          Text(selectedConnectionLabel).lineLimit(1)
          Image(systemName: "chevron.up.chevron.down")
        }
        .font(.caption.weight(.semibold))
      }
      .accessibilityIdentifier("thread.harness")
      .disabled(acting || !store.canMutate)
      HStack(alignment: .bottom, spacing: 8) {
        TextField("Message", text: $reply, axis: .vertical).lineLimit(1...6)
          .focused($composing)
          .accessibilityIdentifier("thread.message")
        Button { Task { await sendReply() } } label: {
          Image(systemName: "arrow.up.circle.fill").font(.title2)
        }
        .accessibilityLabel("Send")
        .disabled(acting || detail.isEmpty || !store.canMutate || !store.permissions.contains("tasks") || reply.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
      }
      if pendingHold && !issue.isEmpty {
        Button("Try again") {
          pendingHold = false
          issue = ""
          Task { await deliverPending() }
        }.font(.caption.weight(.semibold))
      }
    }
    .padding(.horizontal, 12)
    .padding(.top, 8)
    .padding(.bottom, 6)
    .background(.bar)
  }

  private var selectedConnectionLabel: String {
    if let nextConnection { return connectionLabel(nextConnection) }
    let request = detail.object("request")
    let harness = request.text("harness")
    let model = request.text("model")
    if harness.isEmpty { return "Harness" }
    return model.isEmpty ? harness : harness + " · " + model
  }

  private var selectedRequestConnection: RemoteRecord? {
    let current = detail.object("request").text("harness")
    return connections.first { $0.id == current }
  }

  private func connectionLabel(_ choice: RemoteRecord) -> String {
    let model = choice.text("model")
    return model.isEmpty ? choice.text("name") : choice.text("name") + " · " + model
  }

  private func loadConnections() async {
    guard let api = store.api, !store.isPreview, !job.text("project").isEmpty else { return }
    do {
      connections = try await api.rpc("project.connections", ["project": .string(job.text("project"))]).array.map { RemoteRecord(raw: $0.object) }
      if nextConnection == nil {
        let current = store.profiles.first { $0.text("project") == job.text("project") }?.text("harness")
          ?? detail.object("request").text("harness")
        nextConnection = connections.first { $0.id == current }
      }
    } catch {
      if connections.isEmpty, detail.isEmpty { issue = error.localizedDescription }
    }
  }

  private func chooseHarness(_ choice: RemoteRecord) async {
    guard let api = store.api, !acting else { return }
    let previous = nextConnection
    nextConnection = choice
    acting = true; issue = ""
    defer { acting = false }
    do {
      _ = try await api.rpc("project.connection", [
        "project": .string(job.text("project")), "harness": .string(choice.id),
        "provider": .string(choice.text("provider", "agent")), "model": .string(choice.text("model")),
      ], key: "connection-" + UUID().uuidString)
      await store.refresh()
    } catch {
      nextConnection = previous
      issue = error.localizedDescription
    }
  }

  private func sendReply() async {
    composing = false
    UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
    let text = reply.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !text.isEmpty, !detail.isEmpty else { return }
    pending.append(PendingSend(id: UUID().uuidString, text: text))
    reply = ""
    pendingHold = false
    issue = ""
    await deliverPending()
  }

  private func deliverPending() async {
    guard !acting, !pendingHold, let item = pending.first, !detail.isEmpty, !job.active else { return }
    guard let api = store.api else { return }
    guard let profile = store.profiles.first(where: { $0.text("project") == job.text("project") }) else {
      issue = "Share this project on the Mac before sending."
      pendingHold = true
      return
    }
    acting = true
    defer { acting = false }
    do {
      let mode = detail.object("request").text("interaction_mode", "code")
      let result = try await api.rpc("tasks.start", [
        "profile": .string(profile.id), "prompt": .string(item.text), "parent_id": .string(shownID),
        "interaction_mode": .string(mode.isEmpty ? "code" : mode),
      ], key: item.id).object
      let next = result.text("id")
      guard !next.isEmpty else { throw CompanionError("The Mac returned no run ID. Check Activity before sending again.") }
      pending.removeAll { $0.id == item.id }
      issue = ""
      shownID = next
      await store.refreshActivity()
    } catch is CancellationError { }
    catch {
      let message = error.localizedDescription
      if message.localizedCaseInsensitiveContains("finished task") { return }
      if message.localizedCaseInsensitiveContains("uncertain") {
        await reconcile(item)
        return
      }
      issue = message
      pendingHold = true
    }
  }

  private func reconcile(_ item: PendingSend) async {
    guard let api = store.api else { return }
    do {
      let status = try await api.rpc("companion.request_status", ["key": .string(item.id)]).object
      let next = status.object("result").text("id")
      if !next.isEmpty {
        pending.removeAll { $0.id == item.id }
        issue = ""
        shownID = next
        await store.refreshActivity()
        return
      }
      pending.removeAll { $0.id == item.id }
      pending.insert(PendingSend(id: UUID().uuidString, text: item.text), at: 0)
      issue = "That message was not accepted. Try again."
      pendingHold = true
    } catch {
      issue = error.localizedDescription
      pendingHold = true
    }
  }

  private var approvalCard: some View {
    let snapshot = approvalRequest
    return CompanionCard {
      Label("Your approval is needed", systemImage: "hand.raised.fill").font(.headline).foregroundStyle(CompanionTheme.warning)
      let tool = snapshot.object("tool")
      Text(tool.text("tool", tool.text("name", "Agent action"))).font(.headline)
      let arguments = tool.object("arguments").isEmpty ? tool.object("args") : tool.object("arguments")
      if !arguments.text("command").isEmpty { Text(arguments.text("command")).font(.system(.caption, design: .monospaced)).textSelection(.enabled) }
      if !arguments.text("path").isEmpty { Text(arguments.text("path")).font(.caption).textSelection(.enabled) }
      JSONDetails(title: "Action details", value: .object(tool))
      HStack {
        Button("Approve once") { approvalSnapshot = snapshot; confirmApproval = true }.buttonStyle(CompanionPrimaryButton())
        Button("Deny", role: .destructive) {
          let request = snapshot.text("request_id")
          Task { _ = await act("jobs.approve", ["id": .string(shownID), "request_id": .string(request), "allow": .bool(false)], key: "deny:\(shownID):\(request)") }
        }
      }.disabled(acting || !store.canMutate || !store.permissions.contains("approve"))
    }
  }

  private func load() async {
    guard let api = store.api else { return }
    loadGeneration += 1
    let generation = loadGeneration
    let id = shownID
    do {
      // Catch up in bounded pages; never discard unseen events or replay a mutation.
      var cursor = eventCursor
      var merged = events
      var page = detail
      for _ in 0..<4 {
        page = try await api.rpc("jobs.get", ["id": .string(id), "after": .number(cursor)]).object
        guard generation == loadGeneration, id == shownID else { return }
        let next = page.records("events")
        if !next.isEmpty { merged.append(contentsOf: next) }
        cursor = page.number("next_sequence")
        if !page.flag("has_more_events") { break }
      }
      guard generation == loadGeneration, id == shownID else { return }
      events = merged
      eventCursor = cursor
      detail = page
      if !pendingHold { issue = "" }
      await deliverPending()
    } catch is CancellationError { }
    catch {
      guard generation == loadGeneration, id == shownID else { return }
      if detail.isEmpty { issue = error.localizedDescription }
    }
  }
  private func loadHistory(before: String? = nil) async {
    guard let api = store.api else { return }
    do {
      var params: [String: JSONValue] = ["id": .string(shownID)]
      if let before { params["before"] = .string(before) }
      let history = try await api.rpc("conversations.get", params).object
      earlier = history.records("turns") + earlier
      historyCursor = history.text("earlier")
    } catch is CancellationError { }
    catch { issue = error.localizedDescription }
  }
  private func act(_ method: String, _ params: [String: JSONValue], key: String) async -> Bool {
    guard let api = store.api, store.canMutate, !acting else { return false }
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

struct EvaluationResultCard: View {
  let result: [String: JSONValue]
  var onCompare: ([String: JSONValue]) -> Void = { _ in }
  var body: some View {
    CompanionCard {
      Label("Evaluation evidence", systemImage: "chart.bar.xaxis").font(.headline)
      let evidence = result.object("heldout_eval").isEmpty ? result : result.object("heldout_eval")
      if evidence["live"] == .bool(false) {
        Label("Setup validation only", systemImage: "info.circle").foregroundStyle(CompanionTheme.warning)
        Text("Skipped model calls do not measure harness quality.").font(.caption).foregroundStyle(.secondary)
      }
      let gate = result.object("adoption_gate")
      if !gate.isEmpty {
        Label(gate.flag("accepted") ? "Acceptance checks passed" : "Candidate held for review", systemImage: gate.flag("accepted") ? "checkmark.seal.fill" : "hand.raised.fill")
          .foregroundStyle(gate.flag("accepted") ? CompanionTheme.accent : .orange)
      }
      if !result.text("summary").isEmpty { Text(result.text("summary")) }
      let comparison = result.object("comparison")
      if comparison.flag("available") {
        if let first = comparison.records("candidates").first { OutcomeCounts(counts: first.raw.object("counts")) }
        Button { onCompare(comparison) } label: { Label("Compare task outcomes", systemImage: "arrow.left.arrow.right") }
      } else if !comparison.text("message").isEmpty { Text(comparison.text("message")).font(.caption).foregroundStyle(.secondary) }
      ForEach((evidence["variants"]?.array ?? []).enumerated().map { RemoteRecord(raw: $0.element.object.merging(["id": .string(String($0.offset))]) { old, _ in old }) }) { variant in
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
