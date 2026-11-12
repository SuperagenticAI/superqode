import SwiftUI

struct LocalExecutionPanel: View {
  let value: [String: Any]
  let configure: (Int) -> Void
  private var requests: [[String: Any]] { value["requests"] as? [[String: Any]] ?? [] }
  private var limit: Int { value["concurrency"] as? Int ?? 1 }
  private func seconds(_ value: Any?) -> String {
    guard let n = value as? NSNumber else { return "Not reported" }
    return String(format: "%.2f s", n.doubleValue)
  }
  private func memory(_ value: Any?) -> String {
    guard let n = value as? NSNumber else { return "Unknown" }
    return String(format: "%.1f GB", n.doubleValue)
  }
  var body: some View {
    VStack(alignment: .leading, spacing: 14) {
      HStack {
        Label("Local execution", systemImage: "speedometer").font(.headline)
        Spacer()
        Text("\(requests.filter { string($0, "status") == "generating" }.count) generating · \(requests.filter { string($0, "status") == "queued" }.count) waiting")
          .font(.caption).foregroundStyle(.secondary)
      }
      HStack {
        Text("Simultaneous generations").font(.callout)
        Picker("Simultaneous generations", selection: Binding(get: { limit }, set: configure)) {
          Text("1 · recommended").tag(1); Text("2").tag(2); Text("3").tag(3); Text("4").tag(4)
        }.labelsHidden().frame(width: 180)
      }
      Text("Shared across model turns in this engine, including different threads and projects. Tools release the model slot. More concurrency can increase memory pressure and time to first text; it does not make a single model faster.")
        .font(.caption).foregroundStyle(.secondary)
      let health = value["health"] as? [String: Any] ?? [:]
      HStack(spacing: 18) {
        Label("RAM " + memory(health["total_gb"]), systemImage: "memorychip")
        Text("Available " + memory(health["available_gb"]))
        Text("Swap " + memory(health["swap_used_gb"]))
      }.font(.caption).foregroundStyle(.secondary)
      if let swap = health["swap_used_gb"] as? NSNumber, swap.doubleValue >= 2 {
        Text("Swap is in use. Try fewer concurrent generations, a smaller model or less context before adding memory-heavy workloads.").font(.caption).foregroundStyle(.orange)
      }
      if requests.isEmpty {
        Text("Run a local chat or coding task to see measured timings. Prompts, replies and API keys are not stored in this panel.")
          .font(.callout).foregroundStyle(.secondary)
      } else {
        DisclosureGroup("Recent model turns (\(requests.count))") {
          LazyVStack(alignment: .leading, spacing: 12) {
            ForEach(requests, id: \.projectRowID) { row in
              VStack(alignment: .leading, spacing: 6) {
                HStack {
                  Text(string(row, "model")).font(.callout.weight(.medium)).lineLimit(1).help(string(row, "model"))
                  Spacer()
                  Text(string(row, "status")).font(.caption).foregroundStyle(string(row, "status") == "failed" ? Color.orange : .secondary)
                }
                HStack(spacing: 18) {
                  Text("Queue " + seconds(row["queue_s"]))
                  Text("First output " + seconds(row["first_output_s"]))
                  Text("First text " + seconds(row["first_text_s"]))
                }.font(.caption).foregroundStyle(.secondary)
                HStack(spacing: 18) {
                  Text(string(row, "provider"))
                  Text("Turn " + seconds(row["generation_s"]))
                  if let output = row["output_tokens"] as? Int { Text("\(output.formatted()) output tokens") }
                  else { Text("Output tokens not reported") }
                }.font(.caption).foregroundStyle(.secondary)
                DisclosureGroup("Context and server measurements") {
                  VStack(alignment: .leading, spacing: 4) {
                    Text("Context: \((row["context"] as? Int)?.formatted() ?? "Unknown") · " + string(row, "context_source", "Not reported"))
                    Text("Output limit: \((row["output_limit"] as? Int)?.formatted() ?? "Not reported")")
                    Text("Server loading: " + seconds(row["server_load_s"]) + " · prefill: " + seconds(row["server_prefill_s"]) + " · decoding: " + seconds(row["server_decode_s"]))
                  }.font(.caption).foregroundStyle(.secondary)
                }
              }.padding(12).background(Color.secondary.opacity(0.04), in: RoundedRectangle(cornerRadius: 8))
            }
          }.padding(.top, 8)
        }
      }
      Text("First output can be thinking or tool data. First text is the visible answer. Turn timing includes request preparation and server work; server-only loading/prefill/decode times appear only when reported. Cold and warm turns can differ substantially.")
        .font(.caption2).foregroundStyle(.secondary)
    }.padding(18).brandSurface()
  }
}
