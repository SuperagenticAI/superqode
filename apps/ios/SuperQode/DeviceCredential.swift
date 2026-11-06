import Foundation
import Security

struct DeviceCredential: Codable, Sendable {
  let address: String
  let token: String
  let device: String
}

enum DeviceKeychain {
  private static var query: [String: Any] {
    [kSecClass as String: kSecClassGenericPassword,
      kSecAttrService as String: "dev.superqode.ios.companion", kSecAttrAccount as String: "paired-mac",
      kSecAttrSynchronizable as String: false]
  }
  static func load() throws -> DeviceCredential? {
    var request = query
    request[kSecReturnData as String] = true
    request[kSecMatchLimit as String] = kSecMatchLimitOne
    var result: CFTypeRef?
    let status = SecItemCopyMatching(request as CFDictionary, &result)
    if status == errSecItemNotFound { return nil }
    guard status == errSecSuccess, let data = result as? Data else { throw CompanionError("Cannot read this device's authorization from Keychain. Unlock your iPhone and try again.") }
    return try JSONDecoder().decode(DeviceCredential.self, from: data)
  }
  static func save(_ credential: DeviceCredential) throws {
    let data = try JSONEncoder().encode(credential)
    let attributes: [String: Any] = [kSecValueData as String: data,
      kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly]
    let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
    if status == errSecItemNotFound {
      var request = query
      attributes.forEach { request[$0.key] = $0.value }
      guard SecItemAdd(request as CFDictionary, nil) == errSecSuccess else { throw CompanionError("Could not save device authorization in Keychain. Pair again after unlocking your iPhone.") }
    } else if status != errSecSuccess { throw CompanionError("Could not update this device's Keychain authorization.") }
  }
  static func remove() throws {
    let status = SecItemDelete(query as CFDictionary)
    guard status == errSecSuccess || status == errSecItemNotFound else { throw CompanionError("Could not remove the saved authorization. Unlock the iPhone and retry.") }
  }
}
