import AppKit
import SwiftUI

/// Advisory 5-dimension Merge Risk assessment parsed from `factory.run.inspect`.
struct FactoryMergeRiskSnapshot: Equatable {
  enum Level: String, Equatable {
    case low, medium, high

    init(raw: String) {
      switch raw.lowercased().trimmingCharacters(in: .whitespacesAndNewlines) {
      case "high": self = .high
      case "medium": self = .medium
      default: self = .low
      }
    }

    var title: String {
      switch self {
      case .low: return "Low Risk"
      case .medium: return "Medium Risk"
      case .high: return "High Risk"
      }
    }

    var shortLabel: String {
      switch self {
      case .low: return "LOW"
      case .medium: return "MED"
      case .high: return "HIGH"
      }
    }

    var color: Color {
      switch self {
      case .low: return Color(red: 0.14, green: 0.64, blue: 0.42)
      case .medium: return Color(red: 0.90, green: 0.56, blue: 0.12)
      case .high: return Color(red: 0.85, green: 0.24, blue: 0.26)
      }
    }

    var symbol: String {
      switch self {
      case .low: return "shield.checkered"
      case .medium: return "exclamationmark.shield.fill"
      case .high: return "exclamationmark.octagon.fill"
      }
    }
  }

  struct Category: Equatable, Identifiable {
    let id: String
    let title: String
    let risk: Level
    let summary: String
  }

  let overall: Level
  let fileCount: Int
  let churnLines: Int
  let categories: [Category]
  let gaps: [String]
  let markdown: String

  static func parse(detail: [String: Any]) -> FactoryMergeRiskSnapshot? {
    guard let raw = detail["merge_risk"] as? [String: Any], !raw.isEmpty else { return nil }
    let rows = (raw["categories"] as? [[String: Any]] ?? []).map { item in
      Category(
        id: string(item, "id", string(item, "title")),
        title: string(item, "title"),
        risk: Level(raw: string(item, "risk")),
        summary: string(item, "summary")
      )
    }
    guard !rows.isEmpty else { return nil }
    return FactoryMergeRiskSnapshot(
      overall: Level(raw: string(raw, "overall")),
      fileCount: raw["file_count"] as? Int ?? 0,
      churnLines: raw["churn_lines"] as? Int ?? 0,
      categories: rows,
      gaps: raw["gaps"] as? [String] ?? [],
      markdown: string(raw, "markdown")
    )
  }
}

struct FactoryMergeRiskBadge: View {
  let level: FactoryMergeRiskSnapshot.Level
  @Environment(\.colorSchemeContrast) private var contrast

  var body: some View {
    HStack(spacing: 4) {
      Image(systemName: level.symbol)
        .font(.system(size: 10, weight: .semibold))
      Text(level.title)
        .font(.system(size: 10, weight: .bold))
    }
    .foregroundStyle(contrast == .increased ? Color.primary : level.color)
    .padding(.horizontal, 8)
    .padding(.vertical, 3)
    .background(level.color.opacity(contrast == .increased ? 0.16 : 0.11), in: Capsule())
    .overlay(Capsule().stroke(level.color.opacity(0.28), lineWidth: 0.8))
    .help("Advisory 5-dimension Merge Risk assessment (never overrides SuperGauge verdict)")
  }
}

struct FactoryMergeRiskSection: View {
  let risk: FactoryMergeRiskSnapshot
  @State private var expanded = false

  var body: some View {
    DisclosureGroup(isExpanded: $expanded) {
      VStack(alignment: .leading, spacing: 6) {
        ForEach(risk.categories) { row in
          HStack(alignment: .top, spacing: 8) {
            Text(row.risk.shortLabel)
              .font(.system(size: 9, weight: .bold, design: .monospaced))
              .foregroundStyle(row.risk.color)
              .frame(width: 34)
              .padding(.vertical, 2)
              .background(row.risk.color.opacity(0.12), in: Capsule())
            VStack(alignment: .leading, spacing: 1) {
              Text(row.title).font(.caption.weight(.semibold))
              Text(row.summary)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            }
          }
        }
        if !risk.gaps.isEmpty {
          Divider().padding(.vertical, 2)
          VStack(alignment: .leading, spacing: 3) {
            Text("Gaps to review before merge")
              .font(.caption2.weight(.semibold))
              .foregroundStyle(.secondary)
            ForEach(risk.gaps, id: \.self) { gap in
              HStack(alignment: .top, spacing: 5) {
                Image(systemName: "arrow.right.circle.fill")
                  .font(.system(size: 9))
                  .foregroundStyle(risk.overall.color)
                  .padding(.top, 2)
                Text(gap).font(.caption2).foregroundStyle(.secondary)
              }
            }
          }
        }
      }
      .padding(.top, 6)
    } label: {
      HStack(spacing: 8) {
        Text("Merge Risk (5 dimensions · advisory)")
          .font(.caption.weight(.semibold))
        FactoryMergeRiskBadge(level: risk.overall)
        if risk.fileCount > 0 {
          Text("\(risk.fileCount) files · \(risk.churnLines) lines")
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
      }
    }
    .font(.caption)
  }
}

/// Visual Proof gallery + one-click PR Handoff Markdown copy inside Trial Changes & Checks.
struct FactoryVisualProofView: View {
  let detail: [String: Any]
  @State private var copiedHandoff = false
  @State private var previewImageURL: URL?

  private struct ProofItem: Identifiable {
    let id: String
    let name: String
    let path: String
    let relativePath: String
    let kind: String
  }

  private var proof: [String: Any] { detail["visual_proof"] as? [String: Any] ?? [:] }
  private var summary: String { string(proof, "summary") }
  private var handoffMarkdown: String { string(detail, "handoff_markdown") }
  private var items: [ProofItem] {
    (proof["items"] as? [[String: Any]] ?? []).compactMap { row in
      let path = string(row, "path")
      guard !path.isEmpty else { return nil }
      return ProofItem(
        id: path,
        name: string(row, "name", URL(fileURLWithPath: path).lastPathComponent),
        path: path,
        relativePath: string(row, "relative_path", path),
        kind: string(row, "kind", "image")
      )
    }
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      HStack(spacing: 8) {
        Label("Visual proof & PR handoff", systemImage: "photo.on.rectangle.angled")
          .font(.headline)
        Spacer()
        if !handoffMarkdown.isEmpty {
          Button {
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(handoffMarkdown, forType: .string)
            copiedHandoff = true
          } label: {
            Label(copiedHandoff ? "Copied PR summary" : "Copy PR handoff summary", systemImage: copiedHandoff ? "checkmark" : "doc.on.doc")
          }
          .font(.caption)
        }
      }

      if summary.isEmpty && items.isEmpty {
        Text("No visual proof captured yet. Add the built-in ui-verification skill in Build → Configuration so runs save screenshots or clips to .superqode/factory-proof/ and attach a Visual proof walkthrough.")
          .font(.caption)
          .foregroundStyle(.secondary)
          .fixedSize(horizontal: false, vertical: true)
      } else {
        if !summary.isEmpty {
          Text(summary)
            .font(.caption)
            .textSelection(.enabled)
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.primary.opacity(0.03), in: RoundedRectangle(cornerRadius: 8))
        }
        if !items.isEmpty {
          ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
              ForEach(items) { item in
                proofTile(item)
              }
            }
          }
        }
      }
    }
    .padding(12)
    .frame(maxWidth: .infinity, alignment: .leading)
    .brandSurface(radius: 12)
    .onChange(of: handoffMarkdown) { _, _ in copiedHandoff = false }
    .sheet(isPresented: Binding(get: { previewImageURL != nil }, set: { if !$0 { previewImageURL = nil } })) {
      if let url = previewImageURL {
        VStack(spacing: 0) {
          HStack {
            Text(url.lastPathComponent).font(.headline)
            Spacer()
            Button("Reveal in Finder") { NSWorkspace.shared.activateFileViewerSelecting([url]) }
            Button("Done") { previewImageURL = nil }
          }
          .padding(14)
          Divider()
          if let image = NSImage(contentsOf: url) {
            Image(nsImage: image)
              .resizable()
              .scaledToFit()
              .padding(16)
          } else {
            Text("Unable to preview image.").foregroundStyle(.secondary).padding(24)
          }
        }
        .frame(minWidth: 560, minHeight: 420)
      }
    }
  }

  private func proofTile(_ item: ProofItem) -> some View {
    let url = URL(fileURLWithPath: item.path)
    return Button {
      if item.kind == "image" {
        previewImageURL = url
      } else {
        NSWorkspace.shared.open(url)
      }
    } label: {
      VStack(alignment: .leading, spacing: 5) {
        ZStack {
          RoundedRectangle(cornerRadius: 8, style: .continuous)
            .fill(Color.primary.opacity(0.05))
          if item.kind == "image", let image = NSImage(contentsOf: url) {
            Image(nsImage: image)
              .resizable()
              .scaledToFill()
              .frame(width: 148, height: 92)
              .clipped()
          } else {
            VStack(spacing: 4) {
              Image(systemName: item.kind == "video" ? "play.rectangle.fill" : "photo")
                .font(.title2)
                .foregroundStyle(Brand.purple)
              Text(item.kind.uppercased())
                .font(.caption2.monospaced())
                .foregroundStyle(.secondary)
            }
          }
        }
        .frame(width: 148, height: 92)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        Text(item.name)
          .font(.caption2.weight(.medium))
          .lineLimit(1)
          .frame(width: 148, alignment: .leading)
      }
      .padding(6)
      .outlinedSurface(radius: 10)
    }
    .buttonStyle(.plain)
    .help(item.relativePath)
  }
}
