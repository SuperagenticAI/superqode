import Foundation
import Security
import LocalAuthentication

/// The engine receives public keys and signatures only. Enrollment is explicit.
enum FactoryReleaseSigner {
  static let publicPreference = "factoryReleasePublicKey.v1"
  static let tagPreference = "factoryReleaseKeyTag.v1"
  static var enrolledPublicKey: String { UserDefaults.standard.string(forKey: publicPreference) ?? "" }

  static func enroll() async throws -> String {
    if !enrolledPublicKey.isEmpty { return enrolledPublicKey }
    let result = try await Task.detached(priority: .userInitiated) { () throws -> (String, String) in
      let tag = "dev.superqode.factory.release." + UUID().uuidString
      var error: Unmanaged<CFError>?
      guard let access = SecAccessControlCreateWithFlags(nil,
        kSecAttrAccessibleWhenUnlockedThisDeviceOnly, [.privateKeyUsage, .userPresence], &error) else {
        throw error?.takeRetainedValue() as Error? ?? EngineError(message: "Cannot protect the release key")
      }
      let attrs: [String: Any] = [kSecAttrKeyType as String: kSecAttrKeyTypeECSECPrimeRandom,
        kSecAttrKeySizeInBits as String: 256, kSecAttrTokenID as String: kSecAttrTokenIDSecureEnclave,
        kSecPrivateKeyAttrs as String: [kSecAttrIsPermanent as String: true,
          kSecAttrApplicationTag as String: Data(tag.utf8), kSecAttrAccessControl as String: access]]
      guard let key = SecKeyCreateRandomKey(attrs as CFDictionary, &error),
        let publicKey = SecKeyCopyPublicKey(key),
        let bytes = SecKeyCopyExternalRepresentation(publicKey, &error) as Data? else {
        throw error?.takeRetainedValue() as Error? ?? EngineError(message: "Secure Enclave enrollment is unavailable on this Mac")
      }
      return (tag, bytes.base64EncodedString())
    }.value
    UserDefaults.standard.set(result.0, forKey: tagPreference)
    UserDefaults.standard.set(result.1, forKey: publicPreference)
    return result.1
  }

  static func sign(message: Data) async throws -> String {
    let tag = UserDefaults.standard.string(forKey: tagPreference) ?? ""
    guard !tag.isEmpty else { throw EngineError(message: "Enroll this Mac before approving a factory release") }
    return try await Task.detached(priority: .userInitiated) {
      let context = LAContext()
      context.touchIDAuthenticationAllowableReuseDuration = 0
      defer { context.invalidate() }
      let reason = "Approve applying the exact verified Factory Studio change"
      guard try await context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: reason) else {
        throw EngineError(message: "Release approval was not authenticated")
      }
      var item: CFTypeRef?
      let status = SecItemCopyMatching([kSecClass as String: kSecClassKey,
        kSecAttrKeyType as String: kSecAttrKeyTypeECSECPrimeRandom,
        kSecAttrApplicationTag as String: Data(tag.utf8), kSecReturnRef as String: true,
        kSecUseAuthenticationContext as String: context] as CFDictionary, &item)
      guard status == errSecSuccess, let item else {
        throw EngineError(message: "Cannot access the enrolled release key (\(status))")
      }
      return try signature(message: message, key: (item as! SecKey)).base64EncodedString()
    }.value
  }

  // Shared by ephemeral software-key tests; production enrollment never exports a private key.
  static func signature(message: Data, key: SecKey) throws -> Data {
    var error: Unmanaged<CFError>?
    guard let signature = SecKeyCreateSignature(key, .ecdsaSignatureMessageX962SHA256,
      message as CFData, &error) as Data? else {
      throw error?.takeRetainedValue() as Error? ?? EngineError(message: "Release signing failed")
    }
    return signature
  }
}
