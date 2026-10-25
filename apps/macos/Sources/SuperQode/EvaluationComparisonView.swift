import SwiftUI

/// The engine computes this read-only projection from recorded task evidence.
struct EvaluationComparisonView: View {
  let comparison: [String: Any]
  @State private var selectedCandidate = 0
  @State private var filter = "All"
  @State private var search = ""
  private var candidates: [[String: Any]] { comparison["candidates"] as? [[String: Any]] ?? [] }
  private var selectedIndex: Int { candidates.indices.contains(selectedCandidate) ? selectedCandidate : 0 }
  private var candidate: [String: Any] { candidates.indices.contains(selectedIndex) ? candidates[selectedIndex] : [:] }
  private var rows: [[String: Any]] {
    (candidate["rows"] as? [[String: Any]] ?? []).filter { row in
      let outcome = string(row, "outcome")
      let matches = filter == "All" || (filter == "Regressions" && outcome == "regression")
        || (filter == "Improvements" && outcome == "improvement")
        || (filter == "Incomplete evidence" && (outcome == "unverified" || row["fully_graded"] as? Bool != true))
      return matches && (search.isEmpty || string(row, "id").localizedCaseInsensitiveContains(search))
    }
  }

  var body: some View {
    GroupBox {
      VStack(alignment: .leading, spacing: 14) {
        Label("Task comparison", systemImage: "arrow.left.arrow.right").font(.headline)
        if comparison["available"] as? Bool != true {
          Text(string(comparison, "message", "No task comparison recorded."))
            .font(.callout).foregroundStyle(.secondary)
        } else {
          HStack {
            Text("Baseline: " + string(comparison, "baseline")).font(.callout).lineLimit(1)
              .help(string(comparison, "baseline"))
            Picker("Candidate", selection: Binding(get: { selectedIndex }, set: { selectedCandidate = $0 })) {
              ForEach(Array(candidates.enumerated()), id: \.offset) { index, candidate in
                Text(string(candidate, "name") + " · \(index + 1)").tag(index)
              }
            }.frame(maxWidth: 350)
            Spacer()
            Pill(title: string(comparison, "scope") == "held-out" ? "HELD-OUT" : "EVALUATION")
          }
          let counts = candidate["counts"] as? [String: Any] ?? [:]
          HStack {
            Metric(label: "REGRESSIONS", value: "\(counts["regression"] ?? 0)")
            Metric(label: "IMPROVEMENTS", value: "\(counts["improvement"] ?? 0)")
            Metric(label: "UNCHANGED", value: "\(counts["unchanged"] ?? 0)")
            Metric(label: "UNVERIFIED", value: "\(counts["unverified"] ?? 0)")
          }
          Label(verdict, systemImage: string(candidate, "state") == "compared" ? "info.circle" : "exclamationmark.triangle")
            .font(.callout).foregroundStyle(string(candidate, "state") == "compared" ? Color.secondary : .orange)
          ForEach(candidate["issues"] as? [String] ?? [], id: \.self) { issue in
            Text(issue).font(.caption).foregroundStyle(.orange)
          }
          if (candidate["ungraded_pairs"] as? Int ?? 0) > 0 {
            Text("\(candidate["ungraded_pairs"] as? Int ?? 0) task pairs include ungraded outcomes.")
              .font(.caption).foregroundStyle(.orange)
          }
          Grid(alignment: .leading) {
            GridRow {
              Text("Reported cost")
              Text(amount("baseline_cost_usd", currency: true) + " → " + amount("candidate_cost_usd", currency: true))
              Text("Change: " + delta("cost_delta_usd", currency: true))
            }
            GridRow {
              Text("Duration")
              Text(amount("baseline_duration_seconds") + " → " + amount("candidate_duration_seconds"))
              Text("Change: " + delta("duration_delta_seconds"))
            }
          }.font(.caption.monospaced()).foregroundStyle(.secondary)
          HStack {
            TextField("Find task by ID", text: $search).textFieldStyle(.roundedBorder)
            Picker("Show tasks", selection: $filter) {
              ForEach(["All", "Regressions", "Improvements", "Incomplete evidence"], id: \.self) { Text($0) }
            }.frame(width: 210)
          }
          ScrollView {
            LazyVStack(alignment: .leading, spacing: 10) {
              if rows.isEmpty { Text("No tasks match this filter.").foregroundStyle(.secondary) }
              ForEach(rows, id: \.evaluationRowID) { row in
                DisclosureGroup {
                  VStack(alignment: .leading, spacing: 5) {
                    if !string(row, "reason").isEmpty { Text(string(row, "reason")) }
                    Text("Baseline: " + string(row, "baseline_reason", "No reason recorded."))
                    Text("Candidate: " + string(row, "candidate_reason", "No reason recorded."))
                  }.font(.caption).textSelection(.enabled).padding(.vertical, 6)
                } label: {
                  HStack {
                    Text(string(row, "id")).font(.caption.monospaced()).lineLimit(1).help(string(row, "id"))
                    if string(row, "identity_type") != "string" {
                      Text(string(row, "identity_type")).font(.caption).foregroundStyle(.secondary)
                    }
                    Text(string(row, "split")).font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Text(string(row, "baseline_status") + " → " + string(row, "candidate_status")).font(.caption)
                    Pill(title: string(row, "outcome").uppercased(), color: color(row))
                  }
                }
              }
            }.padding(8)
          }.frame(height: 280)
          Text(string(comparison, "message")).font(.caption).foregroundStyle(.secondary)
          Text("Open full evidence for complete grading details.").font(.caption).foregroundStyle(.secondary)
          if string(comparison, "tasks_hash").isEmpty {
            Text("Suite identity was not recorded; verify the source evidence before drawing conclusions.")
              .font(.caption).foregroundStyle(.orange)
          }
        }
      }.padding(12)
    }
  }

  private var verdict: String {
    switch string(candidate, "state") {
    case "regressed": return "The candidate no longer solves some baseline successes. Review every regression."
    case "incomplete": return "Evidence is incomplete; this comparison cannot establish an improvement."
    default: return "Matched outcomes recorded. Review quality and trade-offs before adopting a candidate."
    }
  }
  private func color(_ row: [String: Any]) -> Color {
    switch string(row, "outcome") {
    case "regression": return .red
    case "improvement": return .green
    case "unverified": return .orange
    default: return .secondary
    }
  }
  private func amount(_ key: String, currency: Bool = false) -> String {
    guard let value = candidate[key] as? Double else { return "Unknown" }
    return currency ? String(format: "$%.4f", value) : String(format: "%.2fs", value)
  }
  private func delta(_ key: String, currency: Bool = false) -> String {
    guard let value = candidate[key] as? Double else { return "Unknown" }
    return currency ? String(format: "%+.4f USD", value) : String(format: "%+.2fs", value)
  }
}

private extension Dictionary where Key == String, Value == Any {
  var evaluationRowID: String { self["key"] as? String ?? projectRowID }
}
