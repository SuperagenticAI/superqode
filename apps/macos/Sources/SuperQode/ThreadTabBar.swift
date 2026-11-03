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
                      Circle().fill(statusColor(string(row, "status"))).frame(width: 6, height: 6)
                      Text(string(row, "conversation_title", string(row, "title", "Conversation")))
                        .font(.system(size: 12, weight: selected ? .semibold : .regular))
                        .lineLimit(1).frame(maxWidth: 175)
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
                  .background(selected ? Color.qAccent.opacity(0.13) : Color.qPanel,
                    in: RoundedRectangle(cornerRadius: 7))
                  .overlay(RoundedRectangle(cornerRadius: 7).stroke(selected ? Color.qAccent : Color.clear))
                  .id(identity)
              }
              if app.selectedJob.isEmpty {
                Text("New conversation").font(.system(size: 12, weight: .semibold))
                  .padding(.horizontal, 12).padding(.vertical, 9)
                  .background(Color.qAccent.opacity(0.13), in: RoundedRectangle(cornerRadius: 7))
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
    }
  }

  private func statusColor(_ status: String) -> Color {
    switch status {
    case "needs_approval": return .orange
    case "running", "queued", "cancelling": return .qAccent
    case "completed": return .green
    case "failed", "interrupted": return .red
    default: return .secondary
    }
  }
}
