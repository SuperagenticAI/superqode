import SwiftUI

enum ComparisonFilter: String, CaseIterable {
  case all = "All", regressions = "Regressions", improvements = "Improvements", incomplete = "Incomplete"
  func includes(_ row: RemoteRecord) -> Bool {
    switch self {
    case .all: return true
    case .regressions: return row.text("outcome") == "regression"
    case .improvements: return row.text("outcome") == "improvement"
    case .incomplete: return row.text("outcome") == "unverified" || !row.flag("fully_graded")
    }
  }
}

func evidenceMetric(_ value: JSONValue?, currency: Bool = false, delta: Bool = false) -> String {
  guard case .number(let number) = value, number.isFinite, delta || number >= 0 else { return "Unknown" }
  if currency { return String(format: delta ? "%+.4f USD" : "$%.4f", number) }
  return String(format: delta ? "%+.2fs" : "%.2fs", number)
}

struct EvaluationComparisonScreen: View {
  let comparison: [String: JSONValue]
  @State private var selected = 0
  @State private var filter = ComparisonFilter.all
  @State private var query = ""
  private var candidates: [RemoteRecord] { comparison.records("candidates") }
  private var candidate: [String: JSONValue] { candidates.indices.contains(selected) ? candidates[selected].raw : [:] }
  private var rows: [RemoteRecord] {
    candidate.records("rows").filter { filter.includes($0) && (query.isEmpty || $0.text("id").localizedCaseInsensitiveContains(query)) }
  }
  var body: some View {
    List {
      Section { ConnectionStatus() }.listRowBackground(Color.clear)
      Section {
        Text("Baseline: " + comparison.text("baseline")).font(.headline)
        Label(comparison.text("scope") == "held-out" ? "Held-out evidence" : "Evaluation evidence", systemImage: "checkmark.seal")
          .foregroundStyle(CompanionTheme.accent)
        Picker("Candidate", selection: $selected) {
          ForEach(Array(candidates.enumerated()), id: \.offset) { index, item in Text(item.text("name", "Candidate") + " · \(index + 1)").tag(index) }
        }
      }.listRowBackground(CompanionTheme.panel)
      Section("Outcome summary") {
        OutcomeCounts(counts: candidate.object("counts"))
        Text(candidate.text("state") == "regressed" ? "The candidate loses baseline successes. Review every regression before adoption." : candidate.text("state") == "incomplete" ? "Evidence is incomplete. This result cannot establish an improvement." : "Matched outcomes are recorded. Review quality and trade-offs before adoption.")
          .foregroundStyle(candidate.text("state") == "compared" ? Color.secondary : CompanionTheme.warning)
        ForEach((candidate["issues"]?.array ?? []).map(\.text), id: \.self) { Text($0).font(.footnote).foregroundStyle(CompanionTheme.warning) }
        if candidate.number("ungraded_pairs") > 0 { Text("\(Int(candidate.number("ungraded_pairs"))) task pairs include ungraded outcomes.").font(.footnote).foregroundStyle(CompanionTheme.warning) }
      }.listRowBackground(CompanionTheme.panel)
      Section("Reported trade-offs") {
        metric("Baseline cost", "baseline_cost_usd", currency: true)
        metric("Candidate cost", "candidate_cost_usd", currency: true)
        metric("Cost change", "cost_delta_usd", currency: true, delta: true)
        metric("Baseline duration", "baseline_duration_seconds")
        metric("Candidate duration", "candidate_duration_seconds")
        metric("Duration change", "duration_delta_seconds", delta: true)
        Text("Unknown is not zero. Reported cost is not a billing guarantee.").font(.caption).foregroundStyle(.secondary)
      }.listRowBackground(CompanionTheme.panel)
      Section("Tasks") {
        Picker("Show tasks", selection: $filter) { ForEach(ComparisonFilter.allCases, id: \.self) { Text($0.rawValue).tag($0) } }
        ForEach(Array(rows.enumerated()), id: \.offset) { _, row in task(row) }
        if rows.isEmpty { Text("No tasks match this filter.").foregroundStyle(.secondary) }
      }.listRowBackground(CompanionTheme.panel)
      Section {
        Text(comparison.text("message", "Recorded evidence is not a promotion decision.")).font(.footnote)
        if comparison.text("tasks_hash").isEmpty { Text("Suite identity was not recorded. Verify source evidence before drawing conclusions.").font(.footnote).foregroundStyle(CompanionTheme.warning) }
      }.listRowBackground(Color.clear)
    }.scrollContentBackground(.hidden).background(CompanionTheme.background)
      .navigationTitle("Task comparison").navigationBarTitleDisplayMode(.inline)
      .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: "Find task by ID")
  }
  private func metric(_ title: String, _ key: String, currency: Bool = false, delta: Bool = false) -> some View {
    let value = evidenceMetric(candidate[key], currency: currency, delta: delta)
    return LabeledContent(title, value: value).font(.subheadline.monospacedDigit())
      .accessibilityElement(children: .ignore).accessibilityLabel(title).accessibilityValue(value)
      .accessibilityIdentifier("comparison." + key)
  }
  private func task(_ row: RemoteRecord) -> some View {
    DisclosureGroup {
      VStack(alignment: .leading, spacing: 8) {
        Text(row.text("reason"))
        Text("Baseline: " + row.text("baseline_reason", "No reason recorded."))
        Text("Candidate: " + row.text("candidate_reason", "No reason recorded."))
      }.font(.footnote).textSelection(.enabled).padding(.vertical, 6)
    } label: {
      VStack(alignment: .leading, spacing: 6) {
        Text(row.text("id")).font(.subheadline.monospaced())
        Text(row.text("baseline_status") + " → " + row.text("candidate_status")).font(.caption)
        Text(row.text("outcome").capitalized + " · " + row.text("split")).font(.caption.weight(.semibold))
          .foregroundStyle(row.text("outcome") == "regression" ? Color.red : row.text("outcome") == "improvement" ? CompanionTheme.accent : Color.secondary)
      }
    }
  }
}

struct OutcomeCounts: View {
  let counts: [String: JSONValue]
  var body: some View {
    LazyVGrid(columns: [GridItem(.adaptive(minimum: 120))], alignment: .leading, spacing: 14) {
      ForEach(["regression", "improvement", "unchanged", "unverified"], id: \.self) { key in
        VStack(alignment: .leading, spacing: 4) {
          Text(String(Int(counts.number(key)))).font(.title2.bold()).monospacedDigit()
          Text(key == "regression" ? "Regressions" : key == "improvement" ? "Improvements" : key.capitalized).font(.caption).foregroundStyle(.secondary)
        }.accessibilityElement(children: .combine)
      }
    }.padding(.vertical, 6)
  }
}
