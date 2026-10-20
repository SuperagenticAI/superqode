import Foundation
import Security

/// App-owned generic passwords in the user's Mac keychain. Nothing is synchronized.
struct CredentialStore {
  let service: String

  init() {
    service =
      ProcessInfo.processInfo.arguments.contains("--smoke-test")
      ? "dev.superqode.macos.credentials.test." + UUID().uuidString
      : "dev.superqode.macos.credentials"
  }

  private func query(_ provider: String) -> [String: Any] {
    [
      kSecClass as String: kSecClassGenericPassword,
      kSecAttrService as String: service,
      kSecAttrAccount as String: provider,
      kSecAttrSynchronizable as String: false,
    ]
  }

  private func failure(_ status: OSStatus) -> EngineError {
    EngineError(
      message: "Keychain: "
        + ((SecCopyErrorMessageString(status, nil) as String?) ?? "Access failed (\(status)).")
        + " You can use a key for this session without saving it.")
  }

  func read(_ provider: String) throws -> String? {
    var request = query(provider)
    request[kSecReturnData as String] = true
    request[kSecMatchLimit as String] = kSecMatchLimitOne
    var result: CFTypeRef?
    let status = SecItemCopyMatching(request as CFDictionary, &result)
    if status == errSecItemNotFound { return nil }
    guard status == errSecSuccess, let data = result as? Data,
      let key = String(data: data, encoding: .utf8)
    else { throw failure(status) }
    return key
  }

  func save(_ provider: String, key: String) throws {
    let attributes = [kSecValueData as String: Data(key.utf8)]
    let status = SecItemUpdate(query(provider) as CFDictionary, attributes as CFDictionary)
    if status == errSecItemNotFound {
      var request = query(provider)
      request[kSecValueData as String] = Data(key.utf8)
      request[kSecAttrLabel as String] = "SuperQode · \(provider)"
      let added = SecItemAdd(request as CFDictionary, nil)
      guard added == errSecSuccess else { throw failure(added) }
    } else if status != errSecSuccess {
      throw failure(status)
    }
  }

  func remove(_ provider: String) throws {
    let status = SecItemDelete(query(provider) as CFDictionary)
    guard status == errSecSuccess || status == errSecItemNotFound else { throw failure(status) }
  }
}
