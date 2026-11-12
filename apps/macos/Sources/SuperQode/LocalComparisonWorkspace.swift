import SwiftUI

/// Local comparisons use the same isolated trials and outcome graders as evaluations.
struct LocalComparisonWorkspace: View {
  @EnvironmentObject var app: Workspace
  var active = true
  @State private var routes: [[String: Any]] = []
  @State private var harnesses: [[String: Any]] = []
  @State private var routeIDs = ["", ""]
  @State private var harnessIDs = ["core", "core"]
  @State private var context = 4096
  @State private var warmup = true
  @State private var tasks = ""
  @State private var plan: [String: Any] = [:]
  @State private var review = false
  @State private var busy = false
  @State private var failure = ""
  @State private var job = ""
  @State private var detail: [String: Any] = [:]
  @State private var after = 0
  @State private var polling = false
  @State private var history: [[String: Any]] = []
  private var running: Bool { ["running", "queued", "cancelling", "needs_approval"].contains(string(detail, "status")) }
  private var ready: Bool { !app.projectID.isEmpty && !app.openingProject }
  private var result: [String: Any] { detail["result"] as? [String: Any] ?? [:] }

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 18) {
        PageTitle(eyebrow: "Local AI", title: "Compare models & harnesses",
          subtitle: "Run the same tasks from the same project snapshot. Compare verified outcomes with measured response times.")
        configuration.disabled(busy || running)
        if busy { ProgressView("Preparing local comparison…").controlSize(.small) }
        if !failure.isEmpty { Text(failure).foregroundStyle(.orange).textSelection(.enabled) }
        if !job.isEmpty { operation }
        if !result.isEmpty { report }
        if !history.isEmpty {
          DisclosureGroup("Previous comparisons") {
            ForEach(history, id: \.projectRowID) { row in
              Button(string(row, "title") + " · " + string(row, "status")) {
                job = string(row, "id"); after = 0; detail = [:]
                Task { await poll() }
              }.disabled(running || busy)
            }
          }
        }
      }.padding(24)
    }
    .task(id: app.projectID + ":" + String(active)) {
      guard active, ready else { return }
      job = ""; detail = [:]; after = 0; plan = [:]
      await load()
      while !Task.isCancelled {
        await poll()
        do { try await Task.sleep(for: .seconds(2)) } catch { return }
      }
    }
    .centeredDialog(isPresented: $review, title: "Review local comparison") {
      ScrollView {
        VStack(alignment: .leading, spacing: 14) {
          Text("Review model and verifier execution").font(.title2)
          ForEach(plan["routes"] as? [[String: Any]] ?? [], id: \.localPlanRowID) { row in
            Text(string(row, "label")).font(.callout)
          }
          Text("Shared context: \(plan["context"] as? Int ?? 0) · response cap: \(plan["max_tokens"] as? Int ?? 0)").font(.caption)
          Text(string(plan, "note")).font(.callout)
          Text("A short warmup is \(warmup ? "enabled" : "disabled"). Cache state is not reset; this is not a cold-start benchmark.").font(.caption)
          let inspection = plan["inspection"] as? [String: Any] ?? [:]
          ForEach(inspection["warnings"] as? [String] ?? [], id: \.self) { Text($0).font(.caption).foregroundStyle(.orange) }
          DisclosureGroup("Verifier commands") {
            ForEach(inspection["repository_checks"] as? [[String: Any]] ?? [], id: \.projectRowID) { check in
              Text(string(check, "id")).font(.headline)
              ForEach(check["commands"] as? [String] ?? [], id: \.self) { command in
                Text(command).font(.caption.monospaced()).textSelection(.enabled)
              }
            }
          }
          HStack {
            Button("Cancel") { review = false }
            Spacer()
            Button("Run comparison") { start() }.buttonStyle(BrandButtonStyle()).disabled(busy || !ready || app.anyActive)
          }
        }.padding(24)
      }.frame(width: 760, height: 580)
    }
  }

  private func compatibleHarnesses(_ index: Int) -> [[String: Any]] {
    let route = routes.first { string($0, "id") == routeIDs[index] }
    guard let allowed = route?["allowed_harnesses"] as? [String] else { return harnesses }
    return harnesses.filter { allowed.contains(string($0, "id")) }
  }

  private var configuration: some View {
    VStack(alignment: .leading, spacing: 14) {
      HStack {
        Label("Same tasks. Independent trials.", systemImage: "arrow.left.arrow.right").font(.headline)
        Spacer()
        Button("Refresh local models") { Task { await load() } }.disabled(!ready)
      }
      Text("Load models in their runtime first. Apple on-device is available when Apple Intelligence is ready; use its Apple on-device configuration and a context of 4,096 or less. Each candidate receives its own trial copy; your project is preserved by the runner.")
        .font(.caption).foregroundStyle(.secondary)
      ForEach(routeIDs.indices, id: \.self) { index in
        HStack {
          Text(index == 0 ? "Baseline" : "Candidate \(index)").font(.callout).frame(width: 95, alignment: .leading)
          Picker("Model \(index + 1)", selection: $routeIDs[index]) {
            Text("Choose local model").tag("")
            ForEach(routes, id: \.projectRowID) { row in Text(string(row, "name")).tag(string(row, "id")) }
          }.labelsHidden()
          Picker("Harness \(index + 1)", selection: $harnessIDs[index]) {
            ForEach(compatibleHarnesses(index), id: \.projectRowID) { row in Text(string(row, "name")).tag(string(row, "id")) }
          }.labelsHidden().frame(width: 170)
            .onChange(of: routeIDs[index]) { _, _ in
              let choices = compatibleHarnesses(index)
              if !choices.contains(where: { string($0, "id") == harnessIDs[index] }) {
                harnessIDs[index] = choices.first.map { string($0, "id") } ?? ""
              }
              if routes.first(where: { string($0, "id") == routeIDs[index] })?["provider"] as? String == "apple-foundation" {
                context = min(context, 4096)
              }
            }
        }
      }
      HStack {
        Button("Add candidate") { routeIDs.append(""); harnessIDs.append("core") }.disabled(routeIDs.count >= 4)
        if routeIDs.count > 2 { Button("Remove last candidate") { routeIDs.removeLast(); harnessIDs.removeLast() } }
        Spacer()
        Picker("Shared context cap", selection: $context) {
          ForEach([2048, 4096, 8192, 16384, 32768], id: \.self) { Text($0.formatted()).tag($0) }
        }.frame(width: 260)
      }
      TextField("Task suite path (optional; otherwise two built-in coding tasks)", text: $tasks).textFieldStyle(.roundedBorder)
      Toggle("Run a short warmup before each candidate", isOn: $warmup).font(.callout)
      Text("Outcomes are graded by fixed checks, not the agent's claim of success. The built-in tasks cover a small slice of coding behavior. Verifiers run code with your user permissions; trial copies are not an OS sandbox.")
        .font(.caption).foregroundStyle(.secondary)
      HStack {
        if !ready { Text("Open a project to compare local configurations.").font(.caption).foregroundStyle(.secondary) }
        if routes.isEmpty && ready { Text("No available coding models found. Check your local server or runtime profile.").font(.caption).foregroundStyle(.secondary) }
        Spacer()
        Button("Review comparison…") { prepare() }.buttonStyle(BrandButtonStyle())
          .disabled(!ready || routeIDs.contains("") || app.anyActive)
      }
    }.padding(18).brandSurface()
  }

  private var operation: some View {
    VStack(alignment: .leading, spacing: 10) {
      HStack {
        if running { ProgressView().controlSize(.small) }
        Text("Comparison · " + string(detail, "status", "loading")).font(.headline)
        Spacer()
        if running { Button("Stop") { app.perform { _ = try await app.engine.call("jobs.cancel", ["id": job]) } } }
      }
      DisclosureGroup("Recent progress and output") {
        Text((detail["events"] as? [[String: Any]] ?? []).compactMap { row -> String? in
          let data = row["data"] as? [String: Any] ?? [:]
          return data["message"] as? String ?? data["text"] as? String
        }.joined(separator: "\n")).font(.caption.monospaced()).textSelection(.enabled)
      }
    }.padding(16).brandSurface()
  }

  private var report: some View {
    VStack(alignment: .leading, spacing: 14) {
      EvaluationComparisonView(comparison: result["comparison"] as? [String: Any] ?? [:])
      ForEach(result["variants"] as? [[String: Any]] ?? [], id: \.localVariantID) { variant in
        let config = variant["local_configuration"] as? [String: Any] ?? [:]
        let observation = config["after"] as? [String: Any] ?? [:]
        let requests = variant["model_requests"] as? [[String: Any]] ?? []
        VStack(alignment: .leading, spacing: 8) {
          Text(string(variant, "harness")).font(.headline)
          Text("\(variant["passed"] ?? 0) passed · \(variant["failed"] ?? 0) failed · \(variant["errors"] ?? 0) errors · \(requests.count) measured model requests").font(.caption)
          let firstText = requests.compactMap { ($0["first_text_s"] as? NSNumber)?.doubleValue }.sorted()
          Text("Median first text: " + (firstText.isEmpty ? "Not reported" : String(format: "%.2f s", (firstText[(firstText.count - 1) / 2] + firstText[firstText.count / 2]) / 2)))
            .font(.callout)
          Text("Runtime version: " + string(observation, "runtime_version", "Not reported") + " · loaded context: " + ((observation["loaded_context"] as? Int)?.formatted() ?? "Not reported"))
            .font(.caption).foregroundStyle(.secondary)
          Text("Cache: " + string(config, "cache_policy") + " · cache reset: no").font(.caption).foregroundStyle(.secondary)
          if config["identity_verified"] as? Bool != true {
            Text("An immutable model revision was not verified. Record the exact artifact before treating this run as reproducible.")
              .font(.caption).foregroundStyle(.orange)
          }
          DisclosureGroup("Reproduction details") {
            Text("Model: " + string(config, "model") + "\nEndpoint: " + string(config, "endpoint") + "\nHarness: " + string(config, "harness_digest") + "\nEffective harness: " + string(config, "effective_harness_sha256"))
              .font(.caption.monospaced()).textSelection(.enabled)
            let artifact = observation["artifact"] as? [String: Any] ?? [:]
            Text("Revision: " + string(artifact, "digest", string(artifact, "revision", "Not reported")) + "\nQuantization: " + string(artifact, "quantization", string(artifact["details"] as? [String: Any] ?? [:], "quantization_level", "Not reported")))
              .font(.caption.monospaced()).textSelection(.enabled)
          }
        }.padding(16).brandSurface()
      }
      Text("Suite: " + string(result, "tasks_hash") + "\nSnapshot: " + string(result["workspace"] as? [String: Any] ?? [:], "snapshot_sha256"))
        .font(.caption2.monospaced()).foregroundStyle(.secondary).textSelection(.enabled)
    }
  }

  private func load() async {
    guard ready, !busy else { return }
    busy = true; defer { busy = false }
    let project = app.projectID
    do {
      let value = try await app.engine.call("local.comparisons.catalog", ["project": project]) as? [String: Any] ?? [:]
      guard project == app.projectID, !Task.isCancelled else { return }
      routes = value["routes"] as? [[String: Any]] ?? []
      harnesses = value["harnesses"] as? [[String: Any]] ?? []
      history = try await app.engine.call("local.comparisons.history", ["project": project]) as? [[String: Any]] ?? []
      guard project == app.projectID, !Task.isCancelled else { return }
      if job.isEmpty, let latest = history.first { job = string(latest, "id"); after = 0 }
      failure = ""
    } catch { if !Task.isCancelled { failure = error.localizedDescription } }
  }
  private func prepare() {
    busy = true; failure = ""
    let project = app.projectID
    Task {
      defer { busy = false }
      do {
        let selections = routeIDs.indices.map { ["route": routeIDs[$0], "harness": harnessIDs[$0]] }
        let value = try await app.engine.call("local.comparisons.prepare", ["project": project, "selections": selections, "context": context, "warmup": warmup, "tasks": tasks]) as? [String: Any] ?? [:]
        guard project == app.projectID else { return }
        plan = value; review = true
      } catch { failure = error.localizedDescription }
    }
  }
  private func start() {
    busy = true
    let project = app.projectID
    Task {
      defer { busy = false }
      do {
        let value = try await app.engine.call("local.comparisons.start", ["project": project, "plan": string(plan, "id"), "expected_digest": string(plan, "digest"), "execute": true, "command_id": UUID().uuidString]) as? [String: Any] ?? [:]
        guard project == app.projectID else { return }
        review = false; job = string(value, "id"); after = 0; detail = [:]
        await poll()
      } catch { failure = error.localizedDescription }
    }
  }
  private func poll() async {
    guard !job.isEmpty, !polling else { return }
    if !detail.isEmpty, !running, detail["has_more_events"] as? Bool != true,
      detail["event_stream_open"] as? Bool != true { return }
    polling = true
    defer { polling = false }
    let identity = job
    do {
      var value = try await app.engine.call("jobs.get", ["id": identity, "after": after]) as? [String: Any] ?? [:]
      guard identity == job, !Task.isCancelled else { return }
      let page = try JobEventPage(value, after: after)
      after = page.nextSequence
      value["events"] = Array(((detail["events"] as? [[String: Any]] ?? []) + page.events).suffix(60))
      let finished = (detail.isEmpty || running) && !["running", "queued", "cancelling", "needs_approval"].contains(string(value, "status"))
      if !NSDictionary(dictionary: detail).isEqual(to: value) { detail = value }
      if finished { history = try await app.engine.call("local.comparisons.history", ["project": app.projectID]) as? [[String: Any]] ?? [] }
    } catch { if !Task.isCancelled { failure = error.localizedDescription } }
  }
}

private extension Dictionary where Key == String, Value == Any {
  var localVariantID: String { self["harness"] as? String ?? "" }
  var localPlanRowID: String { self["label"] as? String ?? "" }
}
