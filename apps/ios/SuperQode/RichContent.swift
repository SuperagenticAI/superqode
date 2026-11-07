import SwiftUI
import UIKit

enum MobilePreparedBlock {
  case paragraph(AttributedString), heading(Int, AttributedString), code(String, String)
  case item(String, AttributedString), quote(AttributedString), table([[AttributedString]]), rule
}

struct MobileDocument {
  let source: String
  let blocks: [MobilePreparedBlock]
}

func prepareMobileDocument(_ source: String) async -> MobileDocument? {
  let worker = Task.detached(priority: .userInitiated) { () -> MobileDocument? in
    var blocks: [MobilePreparedBlock] = []
    for block in responseBlocks(source) {
      guard !Task.isCancelled else { return nil }
      switch block {
      case .paragraph(let text): blocks.append(.paragraph(responseInline(text)))
      case .heading(let level, let text): blocks.append(.heading(level, responseInline(text)))
      case .code(let language, let code): blocks.append(.code(language, code))
      case .item(let marker, let text): blocks.append(.item(marker, responseInline(text)))
      case .quote(let text): blocks.append(.quote(responseInline(text)))
      case .table(let rows): blocks.append(.table(rows.map { $0.map(responseInline) }))
      case .rule: blocks.append(.rule)
      }
    }
    return MobileDocument(source: source, blocks: blocks)
  }
  return await withTaskCancellationHandler { await worker.value } onCancel: { worker.cancel() }
}

struct AssistantText: View, Equatable {
  let text: String
  @State private var prepared: MobileDocument?
  static func == (lhs: Self, rhs: Self) -> Bool { lhs.text == rhs.text }
  var body: some View {
    let matches = prepared.map { text.hasPrefix($0.source) } ?? false
    let blocks = matches ? prepared?.blocks ?? [] : []
    VStack(alignment: .leading, spacing: 14) {
      ForEach(Array(blocks.enumerated()), id: \.offset) { _, block in
        switch block {
        case .paragraph(let value): Text(value).lineSpacing(4).textSelection(.enabled)
        case .heading(let level, let value): Text(value).font(level < 3 ? .title3.bold() : .headline).padding(.top, 4)
        case .code(let language, let value): MobileCodeBlock(code: value, language: language).equatable()
        case .item(let marker, let value): HStack(alignment: .firstTextBaseline, spacing: 10) { Text(marker).foregroundStyle(.secondary); Text(value).textSelection(.enabled) }
        case .quote(let value): HStack(spacing: 12) { RoundedRectangle(cornerRadius: 2).fill(CompanionTheme.accent).frame(width: 3); Text(value).foregroundStyle(.secondary).textSelection(.enabled) }.fixedSize(horizontal: false, vertical: true)
        case .table(let rows):
          ScrollView(.horizontal) {
            Grid(alignment: .topLeading, horizontalSpacing: 18, verticalSpacing: 10) {
              ForEach(Array(rows.enumerated()), id: \.offset) { index, row in
                GridRow { ForEach(Array(row.enumerated()), id: \.offset) { _, cell in Text(cell).fontWeight(index == 0 ? .semibold : .regular) } }
              }
            }.font(.subheadline).padding(12)
          }.background(CompanionTheme.background, in: RoundedRectangle(cornerRadius: 12))
        case .rule: Divider()
        }
      }
      let remainder = matches ? String(text.dropFirst(prepared?.source.count ?? 0)) : text
      if !remainder.isEmpty { Text(remainder).textSelection(.enabled).lineSpacing(4) }
    }
    .task(id: text) {
      if let next = await prepareMobileDocument(text), !Task.isCancelled { prepared = next }
    }
    .environment(\.openURL, OpenURLAction { url in
      ["https", "http", "mailto"].contains(url.scheme?.lowercased() ?? "") ? .systemAction : .discarded
    })
  }
}

struct SourceSpan: Equatable {
  enum Kind { case string, comment, keyword, number, addition, deletion, header }
  let range: NSRange
  let kind: Kind
}

func mobileSourceSpans(_ code: String, language: String = "") -> [SourceSpan] {
  if language == "diff" {
    var spans: [SourceSpan] = []
    var offset = 0
    for line in code.components(separatedBy: "\n") {
      let count = line.utf16.count
      let kind: SourceSpan.Kind? = line.hasPrefix("+++") || line.hasPrefix("---") || line.hasPrefix("@@") ? .header
        : line.hasPrefix("+") ? .addition : line.hasPrefix("-") ? .deletion : nil
      if let kind { spans.append(SourceSpan(range: NSRange(location: offset, length: count), kind: kind)) }
      offset += count + 1
    }
    return spans
  }
  let pattern = #"("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(//[^\n]*|#[^\n]*)|\b(async|await|actor|class|struct|enum|func|def|let|var|return|if|else|guard|try|catch|throw|import|from|for|while|in|public|private|static|const|function|export|true|false|nil|None|True|False|null)\b|\b(\d+(?:\.\d+)?)\b"#
  guard let regex = try? NSRegularExpression(pattern: pattern) else { return [] }
  var spans: [SourceSpan] = []
  regex.enumerateMatches(in: code, range: NSRange(code.startIndex..., in: code)) { match, _, stop in
    if Task.isCancelled { stop.pointee = true; return }
    guard let match else { return }
    let kind: SourceSpan.Kind = match.range(at: 1).location != NSNotFound ? .string
      : match.range(at: 2).location != NSNotFound ? .comment
      : match.range(at: 3).location != NSNotFound ? .keyword : .number
    spans.append(SourceSpan(range: match.range, kind: kind))
  }
  return spans
}

struct PreparedMobileSource: @unchecked Sendable {
  let id = UUID()
  let text: NSAttributedString
}

func prepareMobileSource(_ code: String, language: String = "", highContrast: Bool) async -> PreparedMobileSource? {
  let worker = Task.detached(priority: .userInitiated) { () -> PreparedMobileSource? in
    let font = UIFontMetrics(forTextStyle: .caption1).scaledFont(for: .monospacedSystemFont(ofSize: 13, weight: .regular))
    let value = NSMutableAttributedString(string: code, attributes: [.font: font, .foregroundColor: UIColor.label])
    if !highContrast {
      for span in mobileSourceSpans(code, language: language) {
        guard !Task.isCancelled else { return nil }
        let color: UIColor
        switch span.kind {
        case .string: color = .systemGreen
        case .comment: color = .secondaryLabel
        case .keyword: color = .systemPurple
        case .number: color = .systemOrange
        case .addition: color = .systemGreen
        case .deletion: color = .systemRed
        case .header: color = .systemBlue
        }
        value.addAttribute(.foregroundColor, value: color, range: span.range)
      }
    }
    return Task.isCancelled ? nil : PreparedMobileSource(text: NSAttributedString(attributedString: value))
  }
  return await withTaskCancellationHandler { await worker.value } onCancel: { worker.cancel() }
}

struct NativeSourceText: UIViewRepresentable {
  let code: String
  let prepared: PreparedMobileSource?
  func makeUIView(context: Context) -> UITextView {
    let view = UITextView(usingTextLayoutManager: true)
    view.isEditable = false
    view.isSelectable = true
    view.backgroundColor = .clear
    view.textContainerInset = UIEdgeInsets(top: 12, left: 8, bottom: 12, right: 8)
    view.font = UIFontMetrics(forTextStyle: .caption1).scaledFont(for: .monospacedSystemFont(ofSize: 13, weight: .regular))
    view.adjustsFontForContentSizeCategory = true
    view.accessibilityLabel = "Source code"
    return view
  }
  func makeCoordinator() -> Coordinator { Coordinator() }
  func updateUIView(_ view: UITextView, context: Context) {
    if context.coordinator.source != code || context.coordinator.rendered != prepared?.id {
      let offset = view.contentOffset
      if let prepared { view.attributedText = prepared.text } else { view.text = code }
      view.setContentOffset(offset, animated: false)
      context.coordinator.source = code
      context.coordinator.rendered = prepared?.id
    }
  }
  final class Coordinator { var source = ""; var rendered: UUID? }
}

struct MobileCodeBlock: View, Equatable {
  let code: String
  var language = ""
  var fullHeight = false
  @Environment(\.colorSchemeContrast) private var contrast
  @Environment(\.colorScheme) private var scheme
  @State private var prepared: PreparedMobileSource?
  @State private var preparedCode = ""
  @State private var copied = false
  static func == (lhs: Self, rhs: Self) -> Bool { lhs.code == rhs.code && lhs.language == rhs.language && lhs.fullHeight == rhs.fullHeight }
  var body: some View {
    VStack(spacing: 0) {
      HStack {
        Text(language.isEmpty ? "Code" : language).font(.caption.weight(.medium)).foregroundStyle(.secondary)
        Spacer()
        Button { PrivateClipboard.copy(code); copied = true } label: { Label(copied ? "Copied" : "Copy", systemImage: copied ? "checkmark" : "doc.on.doc") }.font(.caption)
      }.padding(.horizontal, 12).padding(.vertical, 10)
      Divider()
      NativeSourceText(code: code, prepared: preparedCode == code ? prepared : nil)
        .frame(height: fullHeight ? nil : min(320, max(90, CGFloat(code.reduce(1) { $1 == "\n" ? $0 + 1 : $0 }) * 18 + 24)))
        .frame(maxHeight: fullHeight ? CGFloat.infinity : nil)
    }.background(CompanionTheme.background, in: RoundedRectangle(cornerRadius: 12))
      .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Color.primary.opacity(0.12)))
      .task(id: code + ":" + String(contrast == .increased) + ":" + String(scheme == .dark)) {
        if let value = await prepareMobileSource(code, language: language, highContrast: contrast == .increased), !Task.isCancelled {
          prepared = value; preparedCode = code
        }
      }
      .onChange(of: code) { _, _ in copied = false }
  }
}
