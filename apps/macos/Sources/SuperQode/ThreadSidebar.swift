import AppKit
import SwiftUI

enum ThreadListFilter: String, CaseIterable {
  case all = "All", working = "Working", needsYou = "Needs you", pinned = "Pinned"
  func matches(_ row: [String: Any]) -> Bool {
    switch self {
    case .all: return true
    case .working: return ["running", "queued", "cancelling"].contains(string(row, "status"))
    case .needsYou: return string(row, "status") == "needs_approval"
    case .pinned: return row["pinned"] as? Bool == true
    }
  }
  static func search(_ query: String, in row: [String: Any]) -> Bool {
    let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
    return trimmed.isEmpty || [string(row, "conversation_title"), string(row, "title"),
      string(row, "kind"), string(row, "status"), ThreadStatusIndicator.title(string(row, "status")),
      HarnessIdentity.used(in: row).map(\.name).joined(separator: " ")]
      .joined(separator: " ").localizedCaseInsensitiveContains(trimmed)
  }
}

struct ThreadHarnessIcons: View {
  let row: [String: Any]
  var size: CGFloat = 24
  var limit = 2
  var body: some View {
    if !HarnessIdentity.used(in: row).isEmpty {
      HarnessIconStack(row: row, size: size, limit: limit, emphasizeCurrent: false).fixedSize()
    } else {
      Image(systemName: string(row, "kind") == "evaluation" ? "checkmark.seal" : string(row, "kind") == "tool" ? "wrench.and.screwdriver" : "cpu")
        .font(.system(size: size * 0.5)).frame(width: size, height: size)
        .foregroundStyle(.secondary).background(Color.primary.opacity(0.06), in: RoundedRectangle(cornerRadius: 6))
        .help("Harness identity was not recorded").accessibilityLabel("Harness identity not recorded")
    }
  }
}

struct ThreadStatusIndicator: View {
  let status: String
  static func title(_ status: String) -> String {
    switch status {
    case "needs_approval": return "Needs you"
    case "running": return "Working"
    case "queued": return "Queued"
    case "cancelling": return "Stopping"
    case "completed": return "Done"
    case "failed": return "Failed"
    case "interrupted": return "Interrupted"
    case "cancelled": return "Stopped"
    default: return status.isEmpty ? "Recorded" : status.capitalized
    }
  }
  private static let attentionColor = adaptive(dark: (1, 0.64, 0.20), light: (0.62, 0.31, 0))
  private static let failureColor = adaptive(dark: (1, 0.38, 0.38), light: (0.74, 0.12, 0.18))
  static func color(_ status: String) -> Color {
    switch status {
    case "needs_approval": return attentionColor
    case "running", "queued", "cancelling": return .secondary
    case "completed": return .secondary
    case "failed", "interrupted": return failureColor
    default: return .secondary
    }
  }
  private static func adaptive(dark: (Double, Double, Double), light: (Double, Double, Double)) -> Color {
    Color(nsColor: NSColor(name: nil) { appearance in
      let rgb = appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? dark : light
      return NSColor(srgbRed: rgb.0, green: rgb.1, blue: rgb.2, alpha: 1)
    })
  }
  var body: some View {
    Group {
      if status == "needs_approval" { Image(systemName: "exclamationmark.circle.fill").font(.system(size: 10)) }
      else { Circle().frame(width: 5, height: 5) }
    }.foregroundStyle(Self.color(status)).help(Self.title(status)).accessibilityLabel(Self.title(status))
  }
}

struct SidebarView: View {
  @EnvironmentObject var app: Workspace
  @State private var search = ""
  @State private var filter: ThreadListFilter = .all
  private var rows: [[String: Any]] {
    app.recentConversations.filter { filter.matches($0) && ThreadListFilter.search(search, in: $0) }
  }
  var body: some View {
    VStack(alignment: .leading, spacing: 0) {
      VStack(alignment: .leading, spacing: 14) {
        BrandWordmark().padding(.top, 8)
        HStack(spacing: 8) {
          Menu {
            Button("Open project…", action: app.chooseProject)
            Divider()
            ForEach(app.projects, id: \.projectRowID) { row in
              Button(string(row, "name", URL(fileURLWithPath: string(row, "path")).lastPathComponent)) {
                app.perform { try await app.open(string(row, "path")) }
              }
            }
          } label: {
            Label(string(app.project, "name", "Open project"), systemImage: "folder")
              .font(.system(size: 12, weight: .semibold)).lineLimit(1)
          }.menuStyle(.borderlessButton)
          Spacer(minLength: 0)
          Button(action: app.chooseProject) { Image(systemName: "folder.badge.plus") }
            .buttonStyle(.plain).help("Open another project").accessibilityLabel("Open another project")
        }
        HStack {
          Text("THREADS").font(.system(size: 10, weight: .bold)).tracking(1.4).foregroundStyle(.secondary)
          Text("\(app.recentConversations.count)").font(.system(size: 10, design: .monospaced)).foregroundStyle(.tertiary)
          Spacer()
          Button { app.section = "Threads" } label: { Image(systemName: "list.bullet") }
            .buttonStyle(.plain).help("Open the full thread library").accessibilityLabel("All threads")
          Button { app.selectJob("", targetSection: "Workspace") } label: { Image(systemName: "square.and.pencil") }
            .buttonStyle(.plain).disabled(app.busy).help("New conversation").accessibilityLabel("New conversation")
        }
        HStack(spacing: 6) {
          Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
          TextField("Search threads or harnesses", text: $search).textFieldStyle(.plain).font(.system(size: 11))
            .accessibilityLabel("Search threads or harnesses")
          if !search.isEmpty {
            Button { search = "" } label: { Image(systemName: "xmark.circle.fill") }.buttonStyle(.plain).accessibilityLabel("Clear thread search")
          }
        }.padding(8).background(Color.primary.opacity(0.045), in: RoundedRectangle(cornerRadius: 7))
        HStack(spacing: 3) {
          ForEach(ThreadListFilter.allCases, id: \.self) { item in
            Button { filter = item } label: {
              Text(item.rawValue).font(.system(size: 10, weight: filter == item ? .semibold : .regular))
                .padding(.horizontal, 8).padding(.vertical, 6)
                .foregroundStyle(filter == item ? Color.primary : .secondary)
                .background(filter == item ? Color.primary.opacity(0.07) : Color.clear, in: RoundedRectangle(cornerRadius: 6))
            }.buttonStyle(.plain).accessibilityAddTraits(filter == item ? .isSelected : [])
          }
        }
      }.padding(.horizontal, 16).padding(.top, 16).padding(.bottom, 10)
      Divider().padding(.horizontal, 16)
      ScrollViewReader { scroll in
        ScrollView {
          LazyVStack(spacing: 4) {
            if rows.isEmpty {
              VStack(alignment: .leading, spacing: 8) {
                Text(app.recentConversations.isEmpty ? "Start your first conversation" : "No matching threads").font(.system(size: 12, weight: .medium))
                Text(app.recentConversations.isEmpty ? "Connect an agent and describe a change in Agent Space." : "Try another filter or search by title or harness.")
                  .font(.caption).foregroundStyle(.secondary)
                if !app.recentConversations.isEmpty {
                  Button("Show all threads") { search = ""; filter = .all }.font(.caption).buttonStyle(.plain).foregroundStyle(Color.qAccent)
                }
              }.frame(maxWidth: .infinity, alignment: .leading).padding(12)
            }
            ForEach(rows, id: \.projectRowID) { row in
              ThreadSidebarRow(row: row).id(string(row, "conversation_id", string(row, "id")))
            }
          }.padding(10)
        }.onChange(of: app.selectedConversationID) { _, identity in scroll.scrollTo(identity, anchor: .center) }
      }
      Divider().padding(.horizontal, 16)
      Button(action: app.presentCommandPalette) {
        HStack {
          Image(systemName: "command"); Text("Search actions"); Spacer(); Text("⌘K").foregroundStyle(.tertiary)
        }.font(.system(size: 11)).foregroundStyle(.secondary).padding(.horizontal, 18).padding(.vertical, 12)
      }.buttonStyle(.plain)
      HStack(spacing: 7) {
        Circle().fill(app.connected ? Color.green : Color.orange).frame(width: 5, height: 5)
        Text(app.connected ? "Local engine ready" : "Engine offline").font(.system(size: 10)).foregroundStyle(.secondary)
        Spacer()
      }.padding(.horizontal, 18).padding(.bottom, 15)
    }.frame(maxHeight: .infinity).background(Color.qPanel)
      .onChange(of: app.projectID) { _, _ in search = ""; filter = .all }
  }
}

struct ThreadSidebarRow: View {
  @EnvironmentObject var app: Workspace
  let row: [String: Any]
  @State private var hovered = false
  private var identity: String { string(row, "conversation_id", string(row, "id")) }
  private var title: String { string(row, "conversation_title", string(row, "title", "Conversation")) }
  private var harnessLabel: String {
    return HarnessIdentity.current(in: row)?.name
      ?? (string(row, "kind") == "task" ? "Harness not recorded" : string(row, "kind").capitalized)
  }
  private var selected: Bool { app.selectedConversationID == identity }
  private var pinned: Bool { row["pinned"] as? Bool == true }
  private var status: String { string(row, "status") }
  private var statusTitle: String { ThreadStatusIndicator.title(status) }
  private var rowFill: Color {
    selected ? Color.primary.opacity(0.07) : hovered ? Color.primary.opacity(0.045) : .clear
  }
  private var destination: String {
    switch string(row, "kind") {
    case "tool": return "Tools"
    case "optimization", "tuning": return "Optimization"
    case "evaluation": return "Evaluations"
    default: return "Workspace"
    }
  }
  var body: some View {
    Button(action: openThread) { rowContent }
      .buttonStyle(.plain)
      .onHover { value in hovered = value }
      .help(Text(verbatim: rowDescription))
      .accessibilityLabel(Text(verbatim: rowDescription))
      .accessibilityAddTraits(selected ? .isSelected : [])
  }
  private var unread: Bool { !selected && app.unreadThreads.contains(identity) }
  private var rowDescription: String {
    "\(title), \(harnessLabel), \(statusTitle)" + (unread ? ", unread" : "")
  }
  private func openThread() {
    app.selectJob(string(row, "id"), targetSection: destination)
  }
  private var rowContent: some View {
    HStack(spacing: 9) {
      ThreadHarnessIcons(row: row, size: 27, limit: 2)
      VStack(alignment: .leading, spacing: 5) {
        titleLine
        statusLine
      }
    }.padding(.horizontal, 10).padding(.vertical, 11).contentShape(Rectangle())
      .background(rowFill, in: RoundedRectangle(cornerRadius: 8))
      .overlay(RoundedRectangle(cornerRadius: 8).stroke(selected ? Color.primary.opacity(0.18) : Color.clear))
  }
  private var titleLine: some View {
    HStack(spacing: 5) {
      if unread {
        Circle().fill(Color.qAccent).frame(width: 7, height: 7).help("New activity since you last opened this thread")
      }
      Text(title).font(.system(size: 12, weight: selected || unread ? .semibold : .regular)).lineLimit(1)
      Spacer(minLength: 0)
      if pinned { Image(systemName: "pin.fill").font(.system(size: 8)).foregroundStyle(.secondary) }
    }
  }
  private var statusLine: some View {
    HStack(spacing: 5) {
      Text(harnessLabel).lineLimit(1).foregroundStyle(.secondary).help("Last used harness: " + harnessLabel)
      Spacer(minLength: 2)
      ThreadStatusIndicator(status: status)
      Group {
        if status == "running", let started = RunStats.startDate(row) {
          LiveElapsedText(prefix: "Working for ", since: started)
        } else if let waiting = RunStats.waitingSince(row) {
          LiveElapsedText(prefix: "Waiting for you ", since: waiting, compact: true)
        } else {
          Text(statusTitle)
        }
      }.foregroundStyle(ThreadStatusIndicator.color(status)).lineLimit(1).layoutPriority(1)
    }.font(.system(size: 10))
  }
}
