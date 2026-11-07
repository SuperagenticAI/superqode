import SwiftUI

struct ThreadTabBar: View {
  @EnvironmentObject var app: Workspace

  var body: some View {
    if !app.projectID.isEmpty {
      HStack(spacing: 0) {
        ScrollViewReader { scroll in
          ScrollView(.horizontal) {
            HStack(spacing: 5) {
              ForEach(app.openThreadTabs, id: \.projectRowID) { row in
                let identity = string(row, "conversation_id", string(row, "id"))
                let selected = app.selectedConversationID == identity
                HStack(spacing: 6) {
                  Button {
                    app.selectJob(string(row, "id"), targetSection: "Workspace")
                  } label: {
                    HStack(spacing: 6) {
                      ThreadHarnessIcons(row: row, size: 23, limit: 2)
                      ThreadStatusIndicator(status: string(row, "status"))
                      Text(string(row, "conversation_title", string(row, "title", "Conversation")))
                        .font(.system(size: 12, weight: selected ? .semibold : .regular))
                        .lineLimit(1).frame(maxWidth: 200)
                    }.padding(.leading, 10).padding(.vertical, 9).contentShape(Rectangle())
                  }.buttonStyle(.plain)
                    .help(string(row, "conversation_title", string(row, "title")) + " · " + string(row, "status"))
                    .accessibilityAddTraits(selected ? .isSelected : [])
                  Button { app.closeThreadTab(identity) } label: {
                    Image(systemName: "xmark").font(.system(size: 9, weight: .medium))
                      .padding(6).contentShape(Rectangle())
                  }.buttonStyle(.plain)
                    .accessibilityLabel("Close tab " + string(row, "conversation_title", string(row, "title")))
                    .help("Close tab. The conversation and its work are kept.")
                }.padding(.trailing, 3)
                  .background(selected ? Color.primary.opacity(0.07) : Color.qPanel,
                    in: RoundedRectangle(cornerRadius: 7))
                  .overlay(RoundedRectangle(cornerRadius: 7).stroke(selected ? Color.primary.opacity(0.2) : Color.clear))
                  .id(identity)
              }
              if app.selectedJob.isEmpty {
                HStack(spacing: 7) {
                  if let harness = app.composerHarnessIdentity {
                    HarnessIcon(identity: harness, size: 23)
                  } else {
                    Image(systemName: "bubble.left.and.bubble.right")
                      .foregroundStyle(.secondary).frame(width: 23, height: 23)
                  }
                  Text("New conversation").font(.system(size: 12, weight: .semibold))
                  Text(app.composerHarnessIdentity?.name ?? "No connection")
                    .font(.system(size: 10)).foregroundStyle(Color.secondary)
                    .lineLimit(1)
                }
                  .padding(.horizontal, 12).padding(.vertical, 9)
                  .background(Color.primary.opacity(0.07), in: RoundedRectangle(cornerRadius: 7))
                  .help(app.composerHarnessIdentity.map { "Selected harness: " + $0.name } ?? "No harness connected. Choose a connection before sending a message.")
                  .id("new-conversation")
              }
            }.padding(.horizontal, 12).padding(.vertical, 5)
          }.scrollIndicators(.hidden)
            .onChange(of: app.selectedConversationID) { _, identity in
              scroll.scrollTo(identity.isEmpty ? "new-conversation" : identity, anchor: .center)
            }
        }
        Button { app.selectJob("", targetSection: "Workspace") } label: {
          Image(systemName: "plus").padding(10)
        }.buttonStyle(.plain).help("New conversation")
          .accessibilityLabel("New conversation tab").disabled(app.busy)
        Button { app.section = "Threads" } label: {
          Image(systemName: "list.bullet").padding(10)
        }.buttonStyle(.plain).help("All threads").accessibilityLabel("Show all threads")
      }.disabled(app.openingProject || app.restoringNavigation)
      Divider()
      if !string(app.phoneRunBanner, "id").isEmpty { PhoneRunBanner() }
    }
  }

}

/// A quiet note that the iPhone started work in another conversation.
struct PhoneRunBanner: View {
  @EnvironmentObject var app: Workspace

  var body: some View {
    HStack(spacing: 8) {
      Image(systemName: "iphone").foregroundStyle(.secondary)
      Text("New run from iPhone").font(.caption.weight(.semibold))
      Text(string(app.phoneRunBanner, "title")).font(.caption).foregroundStyle(.secondary).lineLimit(1)
      Spacer()
      Button("Open") { app.openPhoneRun() }.controlSize(.small)
        .accessibilityIdentifier("phone-run.open")
      Button { app.phoneRunBanner = [:] } label: { Image(systemName: "xmark") }
        .buttonStyle(.plain).controlSize(.small).help("Dismiss")
        .accessibilityLabel("Dismiss new run from iPhone")
        .accessibilityIdentifier("phone-run.dismiss")
    }.padding(.horizontal, 12).padding(.vertical, 6)
      .background(Color.primary.opacity(0.04))
      .accessibilityElement(children: .contain)
      .accessibilityIdentifier("phone-run.banner")
    Divider()
  }
}
