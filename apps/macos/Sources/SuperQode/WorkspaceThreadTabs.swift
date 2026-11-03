import Foundation

@MainActor extension Workspace {
  /// One tab per conversation, even when the conversation has several agent turns.
  var openThreadTabs: [[String: Any]] {
    let rows = groupedRecentRuns(projectJobs).filter { string($0, "kind") == "task" }
    return (threadTabsByProject[projectID] ?? []).compactMap { identity in
      rows.first { string($0, "conversation_id", string($0, "id")) == identity }
    }
  }

  func rememberThreadTab(_ row: [String: Any]) {
    guard !projectID.isEmpty, string(row, "project") == projectID,
      string(row, "kind") == "task", row["archived"] as? Bool != true else { return }
    let identity = string(row, "conversation_id", string(row, "id"))
    guard !identity.isEmpty else { return }
    var tabs = threadTabsByProject[projectID] ?? []
    guard !tabs.contains(identity) else { return }
    tabs.append(identity)
    threadTabsByProject[projectID] = tabs
    preferences.set(threadTabsByProject, forKey: "nativeOpenThreadTabs")
  }

  func closeThreadTab(_ identity: String) {
    let visible = openThreadTabs
    let index = visible.firstIndex { string($0, "conversation_id", string($0, "id")) == identity }
    threadTabsByProject[projectID]?.removeAll { $0 == identity }
    preferences.set(threadTabsByProject, forKey: "nativeOpenThreadTabs")
    guard selectedConversationID == identity else { return }
    let remaining = openThreadTabs
    if !remaining.isEmpty {
      let next = remaining[min(index ?? 0, remaining.count - 1)]
      selectJob(string(next, "id"), targetSection: "Workspace")
    } else {
      selectJob("", targetSection: "Workspace")
    }
  }
}
