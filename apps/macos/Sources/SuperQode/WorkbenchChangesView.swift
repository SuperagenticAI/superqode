import SwiftUI

struct WorkbenchChangesView: View {
  @EnvironmentObject var app: Workspace
  @ObservedObject var review: WorkbenchReview
  @Binding var scope: ReviewScope
  var fullReview: () -> Void
  var refresh: () -> Void
  private var diff: String {
    guard let document = review.document else { return "" }
    return document.hunks.map { hunk in
      hunk.header + "\n" + hunk.lines.map { $0.marker + $0.text }.joined(separator: "\n")
    }.joined(separator: "\n")
  }
  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      HStack {
        Text("Changes").font(.system(size: 12, weight: .semibold))
        Spacer()
        Button(action: refresh) { Image(systemName: "arrow.clockwise") }.help("Refresh changes")
        Button(action: fullReview) { Image(systemName: "arrow.up.left.and.arrow.down.right") }.help("Open full review: comments, staging and branch comparison")
      }.buttonStyle(.plain)
      Picker("Change scope", selection: $scope) {
        if !app.selectedJob.isEmpty && string(app.detail, "kind") == "task" { Text("This turn").tag(ReviewScope.turn) }
        Text("Project changes").tag(ReviewScope.uncommitted)
      }.pickerStyle(.segmented).labelsHidden()
      Text(scope == .turn ? "Recorded checkpoint changes from this turn." : "Current project changes, including edits from other work.")
        .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
      if !app.connected {
        Label("Reconnect the local engine to load changes.", systemImage: "exclamationmark.circle").font(.caption).foregroundStyle(.secondary)
      } else if !review.failure.isEmpty {
        Text(review.failure).font(.caption).foregroundStyle(.orange).textSelection(.enabled)
      }
      if review.loading && review.listing == nil {
        ProgressView("Loading changes…").font(.caption)
      } else if let listing = review.listing {
        if listing.files.isEmpty {
          VStack(alignment: .leading, spacing: 8) {
            Text(scope == .turn ? "No recorded file changes in this turn" : "No current project changes").font(.callout.weight(.medium))
            Text(scope == .turn ? "This turn may have answered or inspected without editing. Interrupted turns may not have a sealed checkpoint." : "The project has no changes in this scope.")
              .font(.caption).foregroundStyle(.secondary)
            if scope == .turn { Button("Inspect project changes") { scope = .uncommitted }.font(.caption) }
          }.padding(.vertical, 16)
        } else {
          Text("\(listing.files.count) changed file\(listing.files.count == 1 ? "" : "s")").font(.caption).foregroundStyle(.secondary)
          ScrollView {
            LazyVStack(alignment: .leading, spacing: 3) {
              ForEach(listing.files) { file in
                Button { Task { await review.select(file.id, engine: app.engine) } } label: {
                  HStack(spacing: 7) {
                    Image(systemName: "doc.text")
                    Text(file.path).lineLimit(1).truncationMode(.middle)
                    Spacer(minLength: 0)
                    Text(file.layerTitle).foregroundStyle(.secondary).font(.system(size: 9))
                  }.font(.system(size: 11)).padding(7).contentShape(Rectangle())
                    .background(review.document?.id == file.id ? Color.primary.opacity(0.07) : .clear, in: RoundedRectangle(cornerRadius: 5))
                }.buttonStyle(.plain).help(file.path)
              }
            }
          }.frame(height: min(130, CGFloat(listing.files.count) * 32))
          if listing.truncated || listing.excludedCount > 0 {
            Text("Some files are excluded or truncated. Open full review for details.").font(.caption).foregroundStyle(.orange)
          }
          if review.loadingFile { ProgressView("Loading revision…").font(.caption) }
          if let document = review.document {
            Text(document.path).font(.caption.monospaced()).textSelection(.enabled)
            if !document.issue.isEmpty { Text(document.issue).font(.caption).foregroundStyle(.orange) }
            if document.truncated { Text("Incomplete diff preview. Review the full file before shipping.").font(.caption).foregroundStyle(.orange) }
            if !diff.isEmpty { DiffView(text: diff).frame(maxHeight: .infinity).layoutPriority(1) }
          }
        }
      }
      Spacer(minLength: 0)
      Button("Open full review", action: fullReview).font(.caption)
    }.padding(14).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).background(Color.qPanel)
  }
}
