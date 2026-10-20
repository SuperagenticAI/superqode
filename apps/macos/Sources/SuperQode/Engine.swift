import AppKit
import Foundation

struct EngineError: LocalizedError {
  let message: String
  var errorDescription: String? { message }
}

/// Decode pipe frames on a serial worker, never in the AppKit input loop.
private final class EngineFrames {
  private let queue = DispatchQueue(label: "dev.superqode.engine.read", qos: .userInitiated)
  private var buffer = Data()
  func receive(_ data: Data, deliver: @escaping ([String: Any]) -> Void) {
    queue.async {
      self.buffer.append(data)
      while let newline = self.buffer.firstIndex(of: 10) {
        let line = self.buffer.prefix(upTo: newline)
        if let object = try? JSONSerialization.jsonObject(with: line) as? [String: Any] {
          deliver(object)
        }
        self.buffer.removeSubrange(...newline)
      }
    }
  }
}

/// Inherited pipes only. The application never opens a network port.
@MainActor final class Engine {
  private var process: Process?
  private var input: FileHandle?
  private let frames = EngineFrames()
  private let writer = DispatchQueue(label: "dev.superqode.engine.write", qos: .userInitiated)
  private var sequence = 0
  private var pending: [Int: CheckedContinuation<Any, Error>] = [:]
  private(set) var diagnostics = ""
  var onExit: (() -> Void)?

  func start() throws {
    let resources = Bundle.main.resourceURL ?? URL(fileURLWithPath: ".")
    let bundled = resources.appendingPathComponent("runtime")
    let root =
      ProcessInfo.processInfo.environment["SUPERQODE_SOURCE_ROOT"]
      .map { URL(fileURLWithPath: $0) }
      ?? URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
      .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    let runtime =
      FileManager.default.fileExists(
        atPath: bundled.appendingPathComponent("python/bin/python3").path)
      ? bundled : root.appendingPathComponent("apps/macos/runtime")
    let python = runtime.appendingPathComponent("python/bin/python3")
    let fallback = root.appendingPathComponent(".venv/bin/python")
    let executable = FileManager.default.fileExists(atPath: python.path) ? python : fallback
    guard FileManager.default.isExecutableFile(atPath: executable.path) else {
      throw EngineError(
        message: "Local engine is missing. Build the bundled runtime before opening SuperQode.")
    }
    let state =
      ProcessInfo.processInfo.environment["SUPERQODE_STATE_DIR"]
      ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
      .appendingPathComponent("SuperQode").path
    let child = Process()
    child.executableURL = executable
    child.arguments = ["-u", "-m", "superqode.desktop_service.service", "--state", state]
    var env = ProcessInfo.processInfo.environment
    env["PYTHONPATH"] =
      FileManager.default.fileExists(atPath: runtime.appendingPathComponent("backend").path)
      ? runtime.appendingPathComponent("backend").path : root.appendingPathComponent("src").path
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    env["PATH"] = Self.executablePath(runtime: runtime, inherited: env["PATH"] ?? "/usr/bin:/bin")
    child.environment = env
    let incoming = Pipe()
    let outgoing = Pipe()
    let errors = Pipe()
    child.standardInput = incoming
    child.standardOutput = outgoing
    child.standardError = errors
    input = incoming.fileHandleForWriting
    let frames = self.frames
    outgoing.fileHandleForReading.readabilityHandler = { [weak self] handle in
      let data = handle.availableData
      guard !data.isEmpty else {
        handle.readabilityHandler = nil
        return
      }
      frames.receive(data) { object in
        Task { @MainActor in self?.receive(object) }
      }
    }
    errors.fileHandleForReading.readabilityHandler = { [weak self] handle in
      let data = handle.availableData
      guard !data.isEmpty else {
        handle.readabilityHandler = nil
        return
      }
      Task { @MainActor in
        guard let self else { return }
        self.diagnostics = String(
          (self.diagnostics + String(decoding: data, as: UTF8.self)).suffix(16000))
      }
    }
    child.terminationHandler = { [weak self] _ in
      Task { @MainActor in
        guard let self else { return }
        let waiting = self.pending.values
        self.pending.removeAll()
        for continuation in waiting {
          continuation.resume(
            throwing: EngineError(
              message: "Local engine stopped. Relaunch SuperQode to reconnect. "
                + self.diagnostics.suffix(1000)))
        }
        self.onExit?()
      }
    }
    try child.run()
    process = child
  }

  private func receive(_ object: [String: Any]) {
      guard let id = object["id"] as? Int, let continuation = pending.removeValue(forKey: id)
      else { return }
      if let error = object["error"] {
        continuation.resume(throwing: EngineError(message: String(describing: error)))
      } else {
        continuation.resume(returning: object["result"] ?? NSNull())
      }
  }

  func call(_ method: String, _ params: [String: Any] = [:]) async throws -> Any {
    guard process?.isRunning == true, let input else {
      throw EngineError(message: "Local engine is not running.")
    }
    sequence += 1
    let id = sequence
    return try await withCheckedThrowingContinuation { continuation in
      pending[id] = continuation
      writer.async {
        do {
          var data = try JSONSerialization.data(withJSONObject: [
            "id": id, "method": method, "params": params,
          ])
          guard data.count <= 1_000_000 else {
            throw EngineError(message: "Request exceeds the local protocol limit.")
          }
          data.append(10)
          try input.write(contentsOf: data)
        } catch {
          Task { @MainActor in self.pending.removeValue(forKey: id)?.resume(throwing: error) }
        }
      }
    }
  }
  func stop() {
    try? input?.close()
    // EOF lets the engine cancel remote tasks and record acknowledgements before exiting.
  }
  /// Finder launches do not inherit shell startup files. Discover common tool
  /// managers without executing the user's shell configuration or reading keys.
  static func executablePath(runtime: URL, inherited: String) -> String {
    let home = FileManager.default.homeDirectoryForCurrentUser
    var paths = [runtime.appendingPathComponent("python/bin").path]
    paths += inherited.components(separatedBy: ":").filter { !$0.isEmpty }
    paths += ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
    paths += [".local/bin", ".opencode/bin", ".bun/bin", ".volta/bin", ".asdf/shims",
              ".local/share/mise/shims", ".local/share/fnm/aliases/default/bin"].map {
      home.appendingPathComponent($0).path
    }
    for (folder, suffix) in [(".nvm/versions/node", "bin"), (".local/share/fnm/node-versions", "installation/bin")] {
      let directory = home.appendingPathComponent(folder)
      let versions = (try? FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)) ?? []
      paths += versions.sorted { $0.lastPathComponent.compare($1.lastPathComponent, options: .numeric) == .orderedDescending }
        .map { $0.appendingPathComponent(suffix).path }
    }
    var seen = Set<String>()
    return paths.filter { $0.hasPrefix("/") && seen.insert($0).inserted }.joined(separator: ":")
  }
}

func string(_ row: [String: Any], _ key: String, _ fallback: String = "") -> String {
  row[key] as? String ?? fallback
}
func pretty(_ value: Any?) -> String {
  guard let value else { return "" }
  if let text = value as? String { return text }
  guard JSONSerialization.isValidJSONObject(value),
    let data = try? JSONSerialization.data(
      withJSONObject: value, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
  else { return String(describing: value) }
  return String(decoding: data, as: UTF8.self)
}
