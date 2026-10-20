import AppKit
import SwiftUI

/// A local, non-HTML renderer: agent text never executes scripts or fetches images.
enum ResponseBlock: Equatable {
  case paragraph(String), heading(Int, String), code(String, String)
  case item(String, String), quote(String), table([[String]]), rule
}

func responseBlocks(_ source: String) -> [ResponseBlock] {
  let lines = source.replacingOccurrences(of: "\r\n", with: "\n").components(separatedBy: "\n")
  var blocks: [ResponseBlock] = []
  var paragraph: [String] = []
  var index = 0
  func flush() {
    if !paragraph.isEmpty { blocks.append(.paragraph(paragraph.joined(separator: "\n"))); paragraph = [] }
  }
  func cells(_ line: String) -> [String] {
    var value = line.trimmingCharacters(in: .whitespaces)
    if value.hasPrefix("|") { value.removeFirst() }
    if value.hasSuffix("|") { value.removeLast() }
    return value.components(separatedBy: "|").map { $0.trimmingCharacters(in: .whitespaces) }
  }
  while index < lines.count {
    let line = lines[index]
    let trimmed = line.trimmingCharacters(in: .whitespaces)
    if trimmed.hasPrefix("```") || trimmed.hasPrefix("~~~") {
      flush()
      let marker = String(trimmed.prefix(while: { $0 == trimmed.first! }))
      let language = String(trimmed.dropFirst(marker.count)).trimmingCharacters(in: .whitespaces)
      index += 1
      var code: [String] = []
      while index < lines.count && !lines[index].trimmingCharacters(in: .whitespaces).hasPrefix(marker) {
        code.append(lines[index]); index += 1
      }
      blocks.append(.code(language, code.joined(separator: "\n")))
      if index < lines.count { index += 1 }
      continue
    }
    if trimmed.isEmpty { flush(); index += 1; continue }
    let heading = trimmed.prefix(while: { $0 == "#" }).count
    if (1...6).contains(heading), trimmed.dropFirst(heading).first == " " {
      flush(); blocks.append(.heading(heading, String(trimmed.dropFirst(heading + 1))))
    } else if ["---", "***", "___"].contains(trimmed) {
      flush(); blocks.append(.rule)
    } else if index + 1 < lines.count, !trimmed.contains("|"),
      ["===", "---"].contains(lines[index + 1].trimmingCharacters(in: .whitespaces)) {
      flush(); blocks.append(.heading(lines[index + 1].contains("=") ? 1 : 2, trimmed)); index += 1
    } else if trimmed.contains("|"), index + 1 < lines.count,
      cells(lines[index + 1]).count > 1,
      cells(lines[index + 1]).allSatisfy({ $0.replacingOccurrences(of: ":", with: "").allSatisfy({ $0 == "-" }) && $0.contains("---") }) {
      flush()
      var rows = [cells(trimmed)]
      index += 2
      while index < lines.count && lines[index].contains("|") {
        rows.append(cells(lines[index])); index += 1
      }
      blocks.append(.table(rows)); continue
    } else if trimmed.hasPrefix(">") {
      flush(); blocks.append(.quote(String(trimmed.dropFirst()).trimmingCharacters(in: .whitespaces)))
    } else if let range = trimmed.range(of: #"^(?:[-*+] |\d+[.)] )"#, options: .regularExpression) {
      flush()
      var body = String(trimmed[range.upperBound...])
      var marker = trimmed[range].first?.isNumber == true ? String(trimmed[range]).trimmingCharacters(in: .whitespaces) : "•"
      if body.hasPrefix("[ ] ") { marker = "☐"; body = String(body.dropFirst(4)) }
      if body.lowercased().hasPrefix("[x] ") { marker = "☑"; body = String(body.dropFirst(4)) }
      blocks.append(.item(marker, body))
    } else { paragraph.append(line) }
    index += 1
  }
  flush()
  return blocks
}

func responseInline(_ text: String) -> AttributedString {
  (try? AttributedString(markdown: text, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)))
    ?? AttributedString(text)
}

struct ResponseDocument: View {
  let text: String
  var body: some View {
    VStack(alignment: .leading, spacing: 14) {
      ForEach(Array(responseBlocks(text).enumerated()), id: \.offset) { _, block in
        switch block {
        case .paragraph(let value):
          Text(responseInline(value)).lineSpacing(5).fixedSize(horizontal: false, vertical: true)
        case .heading(let level, let value):
          Text(responseInline(value)).font(.system(size: level == 1 ? 24 : level == 2 ? 20 : 17, weight: .semibold))
            .padding(.top, 6).accessibilityAddTraits(.isHeader)
        case .code(let language, let code): ResponseCodeBlock(language: language, code: code)
        case .item(let marker, let value):
          HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(marker).foregroundStyle(.secondary).frame(minWidth: 18, alignment: .trailing)
            Text(responseInline(value)).lineSpacing(4).fixedSize(horizontal: false, vertical: true)
          }
        case .quote(let value):
          HStack(alignment: .top, spacing: 12) {
            RoundedRectangle(cornerRadius: 2).fill(Color.qAccent.opacity(0.6)).frame(width: 3)
            Text(responseInline(value)).foregroundStyle(.secondary).lineSpacing(4)
          }.fixedSize(horizontal: false, vertical: true).padding(.vertical, 4)
        case .table(let rows):
          ScrollView(.horizontal) {
            Grid(alignment: .topLeading, horizontalSpacing: 20, verticalSpacing: 10) {
              ForEach(Array(rows.enumerated()), id: \.offset) { index, row in
                GridRow {
                  ForEach(Array(row.enumerated()), id: \.offset) { _, value in
                    Text(responseInline(value)).fontWeight(index == 0 ? .semibold : .regular)
                  }
                }
                if index == 0 { Divider().gridCellUnsizedAxes(.horizontal) }
              }
            }.padding(14)
          }.outlinedSurface(radius: 8)
        case .rule: Divider().padding(.vertical, 4)
        }
      }
    }.font(.system(size: 15)).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
  }
}

/// Lightweight lexical colouring for common source languages; unknown languages stay plain.
func highlightedSource(_ code: String, language: String, dark: Bool, highContrast: Bool) -> AttributedString {
  let value = NSMutableAttributedString(string: code, attributes: [.foregroundColor: dark ? NSColor(srgbRed: 0.93, green: 0.95, blue: 0.98, alpha: 1) : NSColor.labelColor])
  guard !highContrast else { return AttributedString(value) }
  let name = language.lowercased().components(separatedBy: CharacterSet(charactersIn: " \t")).first ?? ""
  let supported = ["swift", "python", "py", "javascript", "js", "typescript", "ts", "tsx", "jsx", "json", "bash", "sh", "zsh", "shell", "ruby", "rb", "go", "rust", "rs", "java", "kotlin", "c", "cpp", "c++", "cs", "csharp", "sql", "yaml", "yml", "toml", "css", "html", "xml", "md", "mdx", "markdown"]
  // Untagged fences still receive conservative lexical colouring; explicit prose stays plain.
  guard name.isEmpty || supported.contains(name) else { return AttributedString(value) }
  let purple = dark ? NSColor(srgbRed: 0.83, green: 0.64, blue: 1, alpha: 1) : NSColor(srgbRed: 0.43, green: 0.16, blue: 0.65, alpha: 1)
  let green = dark ? NSColor(srgbRed: 0.62, green: 0.86, blue: 0.64, alpha: 1) : NSColor(srgbRed: 0.13, green: 0.38, blue: 0.19, alpha: 1)
  let blue = dark ? NSColor(srgbRed: 0.48, green: 0.79, blue: 1, alpha: 1) : NSColor.systemBlue
  let comment = dark ? NSColor(srgbRed: 0.65, green: 0.70, blue: 0.76, alpha: 1) : NSColor.secondaryLabelColor
  let number = dark ? NSColor(srgbRed: 1, green: 0.76, blue: 0.49, alpha: 1) : NSColor(srgbRed: 0.55, green: 0.28, blue: 0.08, alpha: 1)
  if ["md", "mdx", "markdown"].contains(name) {
    let markdown = #"(?m)^(#{1,6}\s+[^\n]*|>[^\n]*)|(`[^`\n]+`)|(\*\*[^*\n]+\*\*|__[^_\n]+__)|(\[[^\]]+\]\([^)]+\))"#
    if let regex = try? NSRegularExpression(pattern: markdown) {
      for match in regex.matches(in: code, range: NSRange(location: 0, length: (code as NSString).length)) {
        let color = match.range(at: 1).location != NSNotFound ? purple : match.range(at: 2).location != NSNotFound ? green : match.range(at: 3).location != NSNotFound ? number : blue
        value.addAttribute(.foregroundColor, value: color, range: match.range)
      }
    }
    return AttributedString(value)
  }
  // A single scan prevents comment markers inside quoted strings from stealing their colour.
  let pattern = #"("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|(//[^\n]*|/\*[\s\S]*?\*/|#[^\n]*)|\b(\d+(?:\.\d+)?)\b|\b(import|from|def|class|func|function|let|var|const|return|if|else|elif|for|while|in|of|try|catch|except|finally|throw|throws|async|await|public|private|static|struct|enum|extension|guard|switch|case|break|continue|true|false|True|False|nil|null|None|self|this|new|export|default|SELECT|FROM|WHERE|AND|OR|INSERT|UPDATE|CREATE|TABLE|assert|with|as|pass|raise|yield|lambda|do|override|init|const|val|fn|pub|use|mod|impl|match)\b|\b([A-Za-z_][A-Za-z_0-9]*)(?=\s*\()"#
  if let regex = try? NSRegularExpression(pattern: pattern) {
    for match in regex.matches(in: code, range: NSRange(location: 0, length: (code as NSString).length)) {
      let color: NSColor = match.range(at: 1).location != NSNotFound ? green
        : match.range(at: 2).location != NSNotFound ? comment
        : match.range(at: 3).location != NSNotFound ? number
        : match.range(at: 4).location != NSNotFound ? purple : blue
      value.addAttribute(.foregroundColor, value: color, range: match.range)
    }
  }
  return AttributedString(value)
}

struct ResponseCodeBlock: View {
  let language: String
  let code: String
  @Environment(\.colorSchemeContrast) private var contrast
  @State private var copied = false
  var body: some View {
    VStack(alignment: .leading, spacing: 0) {
      HStack {
        Text(language.isEmpty ? "Code" : language).font(.system(size: 11, weight: .medium, design: .monospaced)).foregroundStyle(.secondary)
        Spacer()
        Button {
          NSPasteboard.general.clearContents()
          NSPasteboard.general.setString(code, forType: .string)
          copied = true
        } label: { Label(copied ? "Copied" : "Copy", systemImage: copied ? "checkmark" : "doc.on.doc") }
          .buttonStyle(.borderless).font(.caption).accessibilityLabel("Copy code")
      }.padding(.horizontal, 14).padding(.vertical, 9)
      Divider()
      ScrollView(.horizontal) {
        Text(highlightedSource(code, language: language, dark: true, highContrast: contrast == .increased))
          .font(.system(size: 13, design: .monospaced)).lineSpacing(3).textSelection(.enabled)
          .fixedSize(horizontal: true, vertical: false).padding(14)
      }
    }.background(Color.black, in: RoundedRectangle(cornerRadius: 10))
      .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.white.opacity(0.16), lineWidth: 1))
      .environment(\.colorScheme, .dark)
      .onChange(of: code) { _, _ in copied = false }
  }
}

struct AgentActivityView: View {
  let events: [[String: Any]]
  let active: Bool
  @State private var expanded = false
  var body: some View {
    DisclosureGroup(isExpanded: $expanded) {
      ScrollView {
        LazyVStack(alignment: .leading, spacing: 10) {
        ForEach(Array(events.enumerated()), id: \.offset) { _, event in
          let data = event["data"] as? [String: Any] ?? [:]
          let payload = data["payload"] as? [String: Any] ?? data
          let name = string(data, "event", string(event, "type"))
          DisclosureGroup {
            if string(event, "type") == "output" {
              ResponseCodeBlock(language: "", code: string(data, "text"))
            } else {
              Text(pretty(payload)).font(.system(size: 12, design: .monospaced))
                .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
            }
          } label: {
            VStack(alignment: .leading, spacing: 3) {
              Text(name.replacingOccurrences(of: "_", with: " ").capitalized).font(.caption.weight(.medium))
              let title = string(payload, "title", string(payload, "command", string(payload, "name")))
              if !title.isEmpty { Text(title).font(.caption.monospaced()).lineLimit(2) }
            }
          }
        }
        }.padding(.top, 10).padding(.trailing, 6)
      }.frame(height: min(180, CGFloat(events.count) * 54))
    } label: {
      HStack(spacing: 8) {
        Image(systemName: "terminal").foregroundStyle(Color.qAccent)
        Text(active ? "Agent activity · Working" : "Agent activity").font(.system(size: 13, weight: .medium))
        Text("\(events.count) events").font(.caption).foregroundStyle(.secondary)
      }
    }.padding(12).outlinedSurface(radius: 9)
  }
}
