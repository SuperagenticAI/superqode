import Foundation

enum JSONValue: Codable, Equatable, Sendable {
  case object([String: JSONValue]), array([JSONValue]), string(String), number(Double), bool(Bool), null

  init(from decoder: Decoder) throws {
    let value = try decoder.singleValueContainer()
    if value.decodeNil() { self = .null }
    else if let result = try? value.decode(Bool.self) { self = .bool(result) }
    else if let result = try? value.decode(String.self) { self = .string(result) }
    else if let result = try? value.decode(Double.self) { self = .number(result) }
    else if let result = try? value.decode([JSONValue].self) { self = .array(result) }
    else { self = .object(try value.decode([String: JSONValue].self)) }
  }
  func encode(to encoder: Encoder) throws {
    var value = encoder.singleValueContainer()
    switch self {
    case .object(let item): try value.encode(item)
    case .array(let item): try value.encode(item)
    case .string(let item): try value.encode(item)
    case .number(let item): try value.encode(item)
    case .bool(let item): try value.encode(item)
    case .null: try value.encodeNil()
    }
  }
  var object: [String: JSONValue] { if case .object(let result) = self { return result }; return [:] }
  var array: [JSONValue] { if case .array(let result) = self { return result }; return [] }
  var text: String { if case .string(let result) = self { return result }; return "" }
  var flag: Bool { if case .bool(let result) = self { return result }; return false }
  var number: Double { if case .number(let result) = self { return result }; return 0 }
  var pretty: String {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
    return (try? String(decoding: encoder.encode(self), as: UTF8.self)) ?? ""
  }
}

extension Dictionary where Key == String, Value == JSONValue {
  func text(_ key: String, _ fallback: String = "") -> String { self[key]?.text.isEmpty == false ? self[key]!.text : fallback }
  func flag(_ key: String) -> Bool { self[key]?.flag ?? false }
  func number(_ key: String) -> Double { self[key]?.number ?? 0 }
  func object(_ key: String) -> [String: JSONValue] { self[key]?.object ?? [:] }
  func records(_ key: String) -> [RemoteRecord] { (self[key]?.array ?? []).map { RemoteRecord(raw: $0.object) } }
}

struct RemoteRecord: Identifiable, Equatable, Sendable {
  let raw: [String: JSONValue]
  var id: String { raw.text("id", String(Int(raw.number("sequence")))) }
  func text(_ key: String, _ fallback: String = "") -> String { raw.text(key, fallback) }
  func flag(_ key: String) -> Bool { raw.flag(key) }
  var active: Bool { ["queued", "running", "needs_approval", "cancelling"].contains(text("status")) }
}

struct CompanionError: LocalizedError {
  let message: String
  let status: Int
  var errorDescription: String? { message }
  init(_ message: String, status: Int = 0) { self.message = message; self.status = status }
}

enum PrivateMacAddress {
  static func parse(_ input: String) throws -> URL {
    guard let value = URLComponents(string: input.trimmingCharacters(in: .whitespacesAndNewlines)),
      value.scheme == "https", let host = value.host?.lowercased(),
      host.hasSuffix(".ts.net"), host.split(separator: ".").count >= 4,
      host.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "." || $0 == "-") }),
      value.port == nil || value.port == 443 || value.port == 47832, value.user == nil, value.password == nil,
      value.path.isEmpty || value.path == "/", value.query == nil, value.fragment == nil,
      let url = URL(string: "https://" + host + (value.port == 47832 ? ":47832" : ""))
    else { throw CompanionError("Enter your Mac's private https://name.tailnet.ts.net address. Public tunnels and HTTP addresses are not supported.") }
    return url
  }
  static func invitation(_ url: URL) throws -> (URL, String) {
    guard let value = URLComponents(url: url, resolvingAgainstBaseURL: false),
      value.scheme == "superqode-companion", value.host == "pair",
      let address = value.queryItems?.first(where: { $0.name == "server" })?.value,
      let code = value.fragment, !code.isEmpty, code.count <= 100
    else { throw CompanionError("This is not a SuperQode pairing invitation. Create a new invitation in the Mac app.") }
    return (try parse(address), code)
  }
}

private final class NoRedirects: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
  func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
    completionHandler(nil)
  }
}

protocol CompanionTransport: Sendable {
  func post(_ path: String, _ payload: [String: JSONValue], key: String?) async throws -> JSONValue
  func rpc(_ method: String, _ params: [String: JSONValue], key: String?) async throws -> JSONValue
}

extension CompanionTransport {
  func post(_ path: String, _ payload: [String: JSONValue]) async throws -> JSONValue {
    try await post(path, payload, key: nil)
  }
  func rpc(_ method: String) async throws -> JSONValue { try await rpc(method, [:], key: nil) }
  func rpc(_ method: String, _ params: [String: JSONValue]) async throws -> JSONValue {
    try await rpc(method, params, key: nil)
  }
}

struct RemoteAPI: CompanionTransport {
  let address: URL
  let token: String?
  private static let session: URLSession = {
    let config = URLSessionConfiguration.ephemeral
    config.urlCache = nil
    config.httpCookieStorage = nil
    config.timeoutIntervalForRequest = 25
    config.timeoutIntervalForResource = 30
    return URLSession(configuration: config, delegate: NoRedirects(), delegateQueue: nil)
  }()

  func post(_ path: String, _ payload: [String: JSONValue], key: String? = nil) async throws -> JSONValue {
    var request = URLRequest(url: address.appendingPathComponent(path))
    request.httpMethod = "POST"
    request.cachePolicy = .reloadIgnoringLocalAndRemoteCacheData
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.setValue("application/json", forHTTPHeaderField: "Accept")
    if let token { request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization") }
    if let key { request.setValue(key, forHTTPHeaderField: "Idempotency-Key") }
    request.httpBody = try JSONEncoder().encode(JSONValue.object(payload))
    let data: Data
    let response: URLResponse
    do { (data, response) = try await Self.session.data(for: request) }
    catch is CancellationError { throw CancellationError() }
    catch let error as URLError where error.code == .cancelled { throw CancellationError() }
    catch { throw CompanionError("Cannot reach your Mac. Check that Tailscale is connected on both devices and the Mac is awake, online and running SuperQode. Refresh activity before retrying a submitted action.") }
    guard let http = response as? HTTPURLResponse, data.count <= 8 * 1024 * 1024 else {
      throw CompanionError("The Mac returned an oversized or invalid response. Inspect this operation on the Mac.")
    }
    guard let envelope = try? JSONDecoder().decode(JSONValue.self, from: data).object else {
      throw CompanionError("The private address did not return the SuperQode API. Verify Tailscale Serve on the Mac.", status: http.statusCode)
    }
    guard (200..<300).contains(http.statusCode) else {
      throw CompanionError(envelope.text("error", "The Mac could not complete this request."), status: http.statusCode)
    }
    guard let result = envelope["result"] else { throw CompanionError("The Mac returned an incomplete response. Update both apps and reconnect.") }
    return result
  }

  func rpc(_ method: String, _ params: [String: JSONValue] = [:], key: String? = nil) async throws -> JSONValue {
    try await post("v1/rpc", ["method": .string(method), "params": .object(params)], key: key)
  }
}
