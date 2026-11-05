import AppKit
import Foundation

/// All markdown parsing is performed away from the UI actor. Prepared values
/// belong to the view, so changing conversations does not grow a global cache.
enum PreparedResponseBlock {
  case paragraph(AttributedString), heading(Int, AttributedString), code(String, String)
  case item(String, AttributedString), quote(AttributedString), table([[AttributedString]]), rule
}

struct PreparedResponseDocument {
  let source: String
  let blocks: [PreparedResponseBlock]

  /// Preserve already formatted streaming content while the next update is
  /// prepared. Replaced content must never show a previous conversation.
  func remainingText(in text: String) -> String? {
    guard text.utf8.starts(with: source.utf8) else { return nil }
    let end = text.utf8.index(text.utf8.startIndex, offsetBy: source.utf8.count)
    guard let boundary = String.Index(end, within: text) else { return nil }
    return String(text[boundary...])
  }
}

func prepareResponseDocument(_ text: String) async -> PreparedResponseDocument? {
  let worker = Task.detached(priority: .userInitiated) { () -> PreparedResponseDocument? in
    var prepared: [PreparedResponseBlock] = []
    for block in responseBlocks(text) {
      guard !Task.isCancelled else { return nil }
      switch block {
      case .paragraph(let value): prepared.append(.paragraph(responseInline(value)))
      case .heading(let level, let value): prepared.append(.heading(level, responseInline(value)))
      case .code(let language, let code): prepared.append(.code(language, code))
      case .item(let marker, let value): prepared.append(.item(marker, responseInline(value)))
      case .quote(let value): prepared.append(.quote(responseInline(value)))
      case .table(let rows): prepared.append(.table(rows.map { $0.map(responseInline) }))
      case .rule: prepared.append(.rule)
      }
    }
    guard !Task.isCancelled else { return nil }
    return PreparedResponseDocument(source: text, blocks: prepared)
  }
  return await withTaskCancellationHandler {
    await worker.value
  } onCancel: { worker.cancel() }
}

struct SourceHighlightKey: Hashable {
  let code: String
  let language: String
  let highContrast: Bool
}

func prepareHighlightedSource(_ key: SourceHighlightKey) async -> AttributedString? {
  let worker = Task.detached(priority: .userInitiated) { () -> AttributedString? in
    guard !Task.isCancelled else { return nil }
    let result = highlightedSource(key.code, language: key.language, dark: true, highContrast: key.highContrast)
    return Task.isCancelled ? nil : result
  }
  return await withTaskCancellationHandler {
    await worker.value
  } onCancel: { worker.cancel() }
}
