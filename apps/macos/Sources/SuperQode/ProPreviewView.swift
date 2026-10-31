import SwiftUI

/// Product preview only. Commercial verification and approval are not implemented here.
struct ProPreviewView: View {
  @State private var showingExample = false

  var body: some View {
    VStack(alignment: .leading, spacing: 14) {
      HStack(alignment: .firstTextBaseline) {
        Text("Release confidence").font(.headline)
        Spacer()
        Text("PLANNED").font(.caption.bold()).foregroundStyle(.secondary)
          .padding(.horizontal, 8).padding(.vertical, 3)
          .background(.quaternary, in: Capsule())
      }
      Text("Build with any agent. Verify with SuperQode. Decide what ships.")
        .font(.callout)
      Text("The Q stands for Quality. Pro is being developed to help people review evidence and decide whether agent-built software is ready to release.")
        .font(.caption).foregroundStyle(.secondary)

      VStack(alignment: .leading, spacing: 12) {
        plannedFeature("Verify the deliverable", icon: "checkmark.shield",
          detail: "Check the exact release candidate against agreed requirements in a protected verification workflow.")
        plannedFeature("Review the evidence", icon: "doc.text.magnifyingglass",
          detail: "See what passed, what failed and what remains unverified before deciding.")
        plannedFeature("Record the decision", icon: "person.crop.circle.badge.checkmark",
          detail: "Keep the approval, artifact identity and supporting evidence together in a SuperGauge quality record.")
      }

      DisclosureGroup("Illustrative release summary", isExpanded: $showingExample) {
        example.padding(.top, 8)
      }
      Text("Preview only. Pro verification, record inspection and team approval controls are not available in this build. Existing coding and harness tools remain available.")
        .font(.caption).foregroundStyle(.secondary)
      Link("Explore the design-partner programme ↗",
        destination: URL(string: "https://superqode.dev/partners")!)
        .font(.callout)
        .help("Open the SuperQode partners page in your browser")
    }
    .accessibilityElement(children: .contain)
  }

  private func plannedFeature(_ title: String, icon: String, detail: String) -> some View {
    HStack(alignment: .top, spacing: 10) {
      Image(systemName: icon).frame(width: 22).foregroundStyle(.secondary)
        .accessibilityHidden(true)
      VStack(alignment: .leading, spacing: 3) {
        Text(title).font(.callout.weight(.medium))
        Text(detail).font(.caption).foregroundStyle(.secondary)
      }
    }
  }

  private var example: some View {
    VStack(alignment: .leading, spacing: 8) {
      Text("EXAMPLE ONLY · NO VERIFICATION HAS RUN")
        .font(.caption2.bold()).foregroundStyle(.secondary)
      Label("Hold for review", systemImage: "pause.circle")
        .font(.callout.bold())
      Text("Example change: update a greeting API").font(.caption)
      Label("Expected greeting: passed", systemImage: "checkmark.circle")
      Label("Empty input: failed", systemImage: "xmark.circle")
      Label("Deployment environment: not verified", systemImage: "questionmark.circle")
      Divider()
      Text("Next step: fix the empty-input behavior and verify the release environment. No approval has been recorded.")
      Text("This fictional summary explains the planned workflow. It is not a quality record, conformance claim or release authorization.")
        .foregroundStyle(.secondary)
    }
    .font(.caption).textSelection(.enabled)
    .padding(12).background(.quaternary, in: RoundedRectangle(cornerRadius: 8))
  }
}
