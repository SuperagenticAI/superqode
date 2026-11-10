import SwiftUI

/// Advanced only. Local AI and the new-thread grid do not offer these choices.
struct RecursiveAgentsView: View {
  @EnvironmentObject var app: Workspace
  @State private var overview: [String: Any] = [:]
  @State private var failure = ""
  @State private var busy = false
  @State private var progress = ""

  private var cards: [[String: Any]] { overview["cards"] as? [[String: Any]] ?? [] }
  private var montyInstalled: Bool { overview["monty_installed"] as? Bool == true }
  private var dockerAvailable: Bool { overview["docker_available"] as? Bool == true }

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 20) {
        PageTitle(
          eyebrow: "RLM, Monty, and A2A",
          title: "Recursive agents",
          subtitle: "A recursive language model can ask child agents to look at part of the work. This page explains the three boundaries. It is not the way to start coding."
        )
        Text("Getting started? Stay on Local AI. Nothing on this page downloads a model, starts a server, or sends a prompt.")
          .font(.callout).foregroundStyle(.secondary)
        if app.projectID.isEmpty {
          Text("Open a project before choosing a boundary.").foregroundStyle(.secondary)
        }
        if cards.isEmpty && !failure.isEmpty {
          Text(failure).foregroundStyle(.orange).textSelection(.enabled)
        }
        ForEach(cards, id: \.projectRowID) { card in
          boundary(card)
        }
        VStack(alignment: .leading, spacing: 10) {
          Text("Talk to another agent (A2A)").font(.headline)
          Text("A2A is the agent-to-agent protocol. It stays off until you add a peer and save. Hosted agents and credit limits stay off until you turn them on. You can also reach one remote agent from Connect, Protocols, without using RLM. If this thread is not already on one of the three boundaries, this selects On this Mac first. That selection does not turn A2A on.")
            .font(.callout).foregroundStyle(.secondary)
          Button("Set up A2A…") { openRouting() }
            .disabled(app.projectID.isEmpty || busy)
        }.padding(16).brandSurface()
        VStack(alignment: .leading, spacing: 10) {
          Text("DeepSeek and Super Agent").font(.headline)
          Text("Super Agent drafts a reviewed harness. Its check prints a template in Monty and is never installed. It does not call a model or load a plugin. DeepSeek Harness is a separate coding backend: DeepSeek owns the loop, and SuperQode hosts it. Install it from Local AI when you want that backend. It is not the DeepSeek plugin market.")
            .font(.callout).foregroundStyle(.secondary)
          HStack {
            Button("Open Super Agent") { app.section = "Super Agent" }
            Button("Open Local AI") { app.section = "Models" }
            Button("Learn the difference") {
              app.learningTopic = LearningTopics.superAgent
              app.showLearningGuide = true
            }
          }
        }.padding(16).brandSurface()
        if !failure.isEmpty, !cards.isEmpty {
          Text(failure).foregroundStyle(.orange).textSelection(.enabled)
        }
      }.padding(28)
    }
    .task { await load() }
  }

  @ViewBuilder private func boundary(_ card: [String: Any]) -> some View {
    let id = string(card, "id")
    VStack(alignment: .leading, spacing: 8) {
      Text(title(for: id)).font(.headline)
      Text(detail(for: id)).font(.callout).foregroundStyle(.secondary)
      Text(string(card, "warning")).font(.caption).foregroundStyle(.secondary)
      Text("Depth \(shown(card, "max_depth")) · children \(shown(card, "max_children")) · parallel \(shown(card, "max_parallel")). A2A starts off.")
        .font(.caption.monospaced()).foregroundStyle(.secondary)
      if id == "rlm-monty" {
        Text("Strands keeps Monty 0.0.23 in its own runtime. This card is SuperQode's Monty 1.x for the read-only kernel. Installing it here does not change Strands, and Strands is not another boundary on this page.")
          .font(.caption).foregroundStyle(.secondary)
      }
      if id == "rlm-docker", !dockerAvailable {
        Text(string(overview, "docker_detail", "Docker is not running.")).font(.caption).foregroundStyle(.orange)
      }
      if id == "rlm-monty", !montyInstalled {
        Button(busy ? "Installing Monty…" : "Install Monty") { Task { await installMonty() } }
          .disabled(busy || !app.connected)
        if !progress.isEmpty { Text(progress).font(.caption).foregroundStyle(.secondary) }
      } else {
        Button("Choose \(title(for: id)) and a model") { start(id) }
          .buttonStyle(BrandButtonStyle())
          .disabled(app.projectID.isEmpty || busy || (id == "rlm-docker" && !dockerAvailable))
      }
    }.padding(16).brandSurface()
  }

  private func title(for id: String) -> String {
    switch id {
    case "rlm-docker": "In Docker"
    case "rlm-monty": "With Monty"
    default: "On this Mac"
    }
  }

  private func detail(for id: String) -> String {
    switch id {
    case "rlm-docker":
      "The Python kernel runs in a container. Writes stay there. Networking is off. Docker has to be running."
    case "rlm-monty":
      "Read-only Python. No files, no shell, and no network. For looking through a repository, not for changing it."
    default:
      "Persistent Python on this Mac. It runs as you, with no approval prompt. It can edit the project and start child agents."
    }
  }

  private func load() async {
    do {
      overview = try await app.engine.call("rlm.overview") as? [String: Any] ?? [:]
      failure = ""
    } catch {
      failure = error.localizedDescription
    }
  }

  private func installMonty() async {
    busy = true
    progress = "Installing Monty…"
    defer { busy = false }
    do {
      let started = try await app.engine.call("rlm.monty.install") as? [String: Any] ?? [:]
      if string(started, "status") == "completed" {
        progress = ""
        await load()
        return
      }
      let id = string(started, "id")
      guard !id.isEmpty else { throw EngineError(message: "Could not start the Monty install.") }
      for _ in 0..<600 {
        try await Task.sleep(for: .seconds(1))
        guard !Task.isCancelled else { return }
        let status = try await app.engine.call("rlm.monty.status", ["id": id]) as? [String: Any] ?? [:]
        if !string(status, "progress").isEmpty { progress = string(status, "progress") }
        let state = string(status, "status")
        if state == "completed" {
          progress = ""
          await load()
          return
        }
        if state == "failed" {
          failure = string(status, "error", "Monty did not finish installing.")
          progress = ""
          return
        }
      }
      failure = "Monty is still installing. Press Install Monty again in a moment."
    } catch {
      failure = error.localizedDescription
      progress = ""
    }
  }

  private func start(_ id: String) {
    app.chooseHarness(id, restoreRemembered: false)
    app.section = "Workspace"
    app.openConnections("menu:models")
  }

  private func openRouting() {
    if !["rlm", "rlm-docker", "rlm-monty"].contains(app.harness) {
      app.chooseHarness("rlm", restoreRemembered: false)
    }
    app.openConnections("configure:rlm-routing")
  }
}

/// Child agents for an RLM or DeepSeek thread. Hidden for every other harness.
struct AgentsInspector: View {
  @EnvironmentObject var app: Workspace
  @State private var snapshot: [String: Any] = [:]
  @State private var failure = ""
  @State private var goal = ""
  @State private var followUp = ""
  @State private var busy = false

  private var deepSeek: Bool {
    ["deepseek-harness", "dsh", "deepseek"].contains(app.harness)
  }
  private var readOnly: Bool { snapshot["read_only"] as? Bool == true }
  private var running: Bool { snapshot["worker_running"] as? Bool == true }
  private var children: [[String: Any]] {
    deepSeek ? RecursiveAgentTranscript.children(app.events) : snapshot["children"] as? [[String: Any]] ?? []
  }

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 14) {
        if deepSeek {
          Text("DeepSeek runs its own child agents. This list shows when one starts and when it finishes.")
            .font(.callout).foregroundStyle(.secondary)
        } else {
          Text(boundaryLine).font(.headline)
          if !string(snapshot, "warning").isEmpty {
            Text(string(snapshot, "warning")).font(.caption).foregroundStyle(.secondary)
          }
          Text("Depth \(shown(snapshot, "max_depth")) · children \(shown(snapshot, "max_children")) · parallel \(shown(snapshot, "max_parallel")). A2A is \(snapshot["a2a"] as? Bool == true ? "on" : "off").")
            .font(.caption.monospaced()).foregroundStyle(.secondary)
          let usage = snapshot["usage"] as? [String: Any] ?? [:]
          Text("\(shown(usage, "children")) child agents · \(shown(usage, "total_tokens")) tokens")
            .font(.caption).foregroundStyle(.secondary)
          if readOnly {
            Text("Monty cannot change files, run a shell command, or start a child agent. Those controls stay off.")
              .font(.callout).foregroundStyle(.secondary)
          } else if !running {
            Text("Follow-up, steer, and cancel reach the worker only while this thread is running. Opening this panel does not start one.")
              .font(.caption).foregroundStyle(.secondary)
          } else {
            Text("A follow-up waits until the current turn finishes.")
              .font(.caption).foregroundStyle(.secondary)
          }
        }
        if children.isEmpty {
          Text(deepSeek ? "No DeepSeek child agent has reported in yet." : "No child agents are recorded for this thread yet.")
            .foregroundStyle(.secondary)
        }
        ForEach(children, id: \.projectRowID) { child in
          VStack(alignment: .leading, spacing: 6) {
            Text(string(child, "id")).font(.system(.body, design: .monospaced))
            Text(string(child, "status")).font(.caption).foregroundStyle(.secondary)
            if !string(child, "prompt").isEmpty { Text(string(child, "prompt")).font(.callout) }
            if !string(child, "error").isEmpty {
              Text(string(child, "error")).font(.caption).foregroundStyle(.orange)
            }
            if !deepSeek, !readOnly, running {
              let messageEmpty = followUp.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
              HStack {
                Button("Steer") {
                  let id = string(child, "id")
                  Task { await send("steer", agent: id) }
                }.disabled(busy || messageEmpty)
                Button("Follow up") {
                  let id = string(child, "id")
                  Task { await send("send", agent: id) }
                }.disabled(busy || messageEmpty)
                Button("Cancel") {
                  let id = string(child, "id")
                  Task { await cancel(id) }
                }.disabled(busy)
              }
            }
          }.padding(12).brandSurface()
        }
        if !deepSeek, !readOnly, running {
          TextField("Message for steer or follow-up", text: $followUp).textFieldStyle(.roundedBorder)
          TextField("Goal. Leave empty to turn it off.", text: $goal).textFieldStyle(.roundedBorder)
          HStack {
            Button("Save goal") {
              let text = goal.trimmingCharacters(in: .whitespacesAndNewlines)
              Task { await run("goal", argument: text.isEmpty ? "off" : text) }
            }
            Button("Autonomous on") { Task { await run("autonomous", argument: "on") } }
            Button("Autonomous off") { Task { await run("autonomous", argument: "off") } }
          }.disabled(busy)
          Text("Autonomous gates stay off until you turn them on. The change waits until the current turn finishes.")
            .font(.caption).foregroundStyle(.secondary)
        }
        if !deepSeek {
          Button("Refresh") { Task { await reload() } }.disabled(busy || app.projectID.isEmpty)
        }
        if !failure.isEmpty { Text(failure).foregroundStyle(.orange).textSelection(.enabled) }
      }.padding(16)
    }
    .task(id: app.projectID + "\n" + app.harness + "\n" + app.selectedJob) { await reload() }
  }

  private var boundaryLine: String {
    switch string(snapshot, "sandbox", app.harness) {
    case "docker", "rlm-docker": "In Docker"
    case "monty", "rlm-monty": "With Monty"
    default: "On this Mac"
    }
  }

  private func reload() async {
    guard !deepSeek, !app.projectID.isEmpty else { return }
    do {
      snapshot = try await app.engine.call("rlm.inspect", [
        "project": app.projectID, "harness": app.harness,
      ]) as? [String: Any] ?? [:]
      failure = ""
    } catch {
      failure = error.localizedDescription
    }
  }

  private func send(_ command: String, agent: String) async {
    let message = followUp.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !agent.isEmpty, !message.isEmpty else {
      failure = "Choose a child and write a message first."
      return
    }
    await run(command, agent: agent, message: message)
  }

  private func cancel(_ id: String) async {
    await run("cancel", agent: id)
  }

  private func run(_ command: String, argument: String = "", agent: String = "", message: String = "") async {
    busy = true
    defer { busy = false }
    var params: [String: Any] = [
      "project": app.projectID, "harness": app.harness, "command": command,
    ]
    if !argument.isEmpty { params["argument"] = argument }
    if !agent.isEmpty { params["agent"] = agent }
    if !message.isEmpty { params["message"] = message }
    do {
      _ = try await app.engine.call("rlm.command", params)
      failure = ""
      app.notice = "Sent to the running RLM worker. It applies when the current turn can take it."
      await reload()
    } catch {
      failure = error.localizedDescription
    }
  }
}

enum RecursiveAgentTranscript {
  static func children(_ events: [[String: Any]]) -> [[String: Any]] {
    var rows: [String: [String: Any]] = [:]
    for event in events where string(event, "type") == "harness_event" {
      let data = event["data"] as? [String: Any] ?? [:]
      guard string(data, "event") == "subagent" else { continue }
      let payload = data["payload"] as? [String: Any] ?? data
      let id = string(payload, "child_session_id", string(payload, "childSessionId"))
      guard !id.isEmpty else { continue }
      let phase = string(payload, "phase")
      let previous = rows[id] ?? [:]
      let parent = string(payload, "parent_session_id", string(previous, "parent_id"))
      rows[id] = [
        "id": id,
        "status": phase == "finished" ? "finished" : "started",
        "prompt": "",
        "error": "",
        "parent_id": parent,
      ]
    }
    return Array(rows.values)
  }
}

private func shown(_ row: [String: Any], _ key: String) -> String {
  switch row[key] {
  case let value as Int: return String(value)
  case let value as Double: return String(Int(value))
  case let value as NSNumber: return String(value.intValue)
  default: return "0"
  }
}
