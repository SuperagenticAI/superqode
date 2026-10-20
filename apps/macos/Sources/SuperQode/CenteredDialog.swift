import SwiftUI

@propertyWrapper struct DialogDismiss: DynamicProperty {
  @Environment(\.dismiss) private var dismiss
  var wrappedValue: () -> Void { { dismiss() } }
}

extension View {
  /// Let SwiftUI/AppKit own presentation, input dispatch and nested-sheet cleanup.
  /// Manually pumping a modal session from a timer bypasses normal interaction.
  func centeredDialog<Dialog: View>(
    isPresented: Binding<Bool>, title: String = "SuperQode",
    @ViewBuilder content: @escaping () -> Dialog
  ) -> some View {
    sheet(isPresented: isPresented) {
      VStack(spacing: 0) {
        HStack {
          Text(title).font(.headline)
          Spacer()
          nativeButton("dialog.close", action: { isPresented.wrappedValue = false }, title: "Close " + title) {
            Image(systemName: "xmark").font(.system(size: 12, weight: .semibold))
          }
        }.padding(.horizontal, 16).padding(.vertical, 10)
        Divider()
        content()
      }
      .background(Color.qPanel)
      .onExitCommand { isPresented.wrappedValue = false }
    }
  }
}
