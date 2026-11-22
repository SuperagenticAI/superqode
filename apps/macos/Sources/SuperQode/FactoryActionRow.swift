import SwiftUI

/// Keep action labels readable when the project sidebar narrows the workspace.
struct FactoryActionRow<Content: View>: View {
  let content: Content
  init(@ViewBuilder content: () -> Content) { self.content = content() }
  var body: some View {
    ViewThatFits(in: .horizontal) {
      HStack(spacing: 8) { content }.fixedSize(horizontal: true, vertical: false)
      VStack(alignment: .leading, spacing: 8) { content }
    }
  }
}
