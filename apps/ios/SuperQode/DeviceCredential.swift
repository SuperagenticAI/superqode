import Foundation
import Security

struct DeviceCredential: Codable, Sendable {
  let address: String
  let token: String
  let device: String
}

enum DeviceKeychain {
  private static func query(_ account: String) -> [String: Any] {
    [kSecClass as String: kSecClassGenericPassword,
      kSecAttrService as String: "dev.superqode.ios.companion", kSecAttrAccount as String: account,
      kSecAttrSynchronizable as String: false]
  }
  private static func failure(_ status: OSStatus) -> CompanionError {
    if status == errSecMissingEntitlement {
      return CompanionError("This build cannot access Keychain. Install an ad-hoc signed simulator build or a development build signed by your team.")
    }
    if status == errSecInteractionNotAllowed {
      return CompanionError("Keychain is locked. Unlock your iPhone and try again.")
    }
    return CompanionError("Device authorization could not be accessed in Keychain (\(status)). Reopen the app and retry; if it persists, check this build's signing configuration.")
  }
  static func load(account: String = "paired-mac") throws -> DeviceCredential? {
    var request = query(account)
    request[kSecReturnData as String] = true
    request[kSecMatchLimit as String] = kSecMatchLimitOne
    var result: CFTypeRef?
    let status = SecItemCopyMatching(request as CFDictionary, &result)
    if status == errSecItemNotFound { return nil }
    guard status == errSecSuccess else { throw failure(status) }
    guard let data = result as? Data else { throw CompanionError("The saved device authorization is invalid. Disconnect and pair this iPhone again.") }
    return try JSONDecoder().decode(DeviceCredential.self, from: data)
  }
  static func save(_ credential: DeviceCredential, account: String = "paired-mac") throws {
    let data = try JSONEncoder().encode(credential)
    let attributes: [String: Any] = [kSecValueData as String: data,
      kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly]
    let status = SecItemUpdate(query(account) as CFDictionary, attributes as CFDictionary)
    if status == errSecItemNotFound {
      var request = query(account)
      attributes.forEach { request[$0.key] = $0.value }
      let added = SecItemAdd(request as CFDictionary, nil)
      guard added == errSecSuccess else { throw failure(added) }
    } else if status != errSecSuccess { throw failure(status) }
  }
  static func remove(account: String = "paired-mac") throws {
    let status = SecItemDelete(query(account) as CFDictionary)
    guard status == errSecSuccess || status == errSecItemNotFound else { throw failure(status) }
  }
}
