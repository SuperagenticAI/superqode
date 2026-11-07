import SwiftUI

/// A neutral website link, with no commercial workflows implemented here.
struct ProPreviewView: View {
  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      Text("For information about SuperQode Pro, visit our website.")
        .font(.caption).foregroundStyle(.secondary)
      Link("Visit the SuperQode website", destination: URL(string: "https://superqode.dev")!)
        .font(.callout)
        .help("Open the SuperQode website in your browser")
    }
    .accessibilityElement(children: .contain)
  }
}
