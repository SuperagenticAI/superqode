import AVFoundation
import SwiftUI
import VisionKit

struct PairMacScreen: View {
  @EnvironmentObject private var store: CompanionStore
  @State private var scanner = false
  @State private var scanIssue = ""
  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 24) {
        Image(systemName: "iphone.and.arrow.forward").font(.system(size: 54, weight: .light))
          .foregroundStyle(LinearGradient(colors: [.cyan, CompanionTheme.accent], startPoint: .topLeading, endPoint: .bottomTrailing))
          .padding(.top, 30).accessibilityHidden(true)
        Text("Your workspace.\nWherever you are.").font(.system(.largeTitle, design: .rounded, weight: .bold))
        Text("Run on your Mac. Review from your iPhone.\nA private connection, with you in control.")
          .foregroundStyle(.secondary)
        if store.waitingForApproval {
          CompanionCard {
            ProgressView()
            Text("Approve this iPhone on your Mac").font(.headline)
            Text("In SuperQode, open Settings → Private remote access and approve the request. Only the selected project connections are shared.")
              .foregroundStyle(.secondary)
            Button("Cancel pairing") { store.cancelPairing() }
          }
        } else {
          CompanionCard {
            Text("Pair with your Mac").font(.title3.bold())
            Text("Enable Tailscale on both devices. Create a pairing invitation in the Mac app's Private remote access settings.")
              .font(.subheadline).foregroundStyle(.secondary)
            Button { Task { await openScanner() } } label: {
              Label("Scan Mac invitation", systemImage: "qrcode.viewfinder").frame(maxWidth: .infinity).padding(.vertical, 8)
            }.buttonStyle(.bordered).disabled(store.connecting)
            if !scanIssue.isEmpty { Text(scanIssue).font(.caption).foregroundStyle(.orange) }
            TextField("https://your-mac.tailnet.ts.net", text: $store.address)
              .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
              .textContentType(.URL).accessibilityLabel("Private Mac address")
            SecureField("Five-minute pairing code", text: $store.pairingCode)
              .textInputAutocapitalization(.never).autocorrectionDisabled()
              .accessibilityLabel("Pairing invitation code")
            TextField("Name this iPhone", text: $store.deviceName)
            Button { store.beginPairing() } label: {
              HStack { if store.connecting { ProgressView() }; Text(store.connecting ? "Connecting…" : "Request Mac approval").fontWeight(.semibold) }
                .frame(maxWidth: .infinity).padding(.vertical, 8)
            }.buttonStyle(.borderedProminent).tint(CompanionTheme.accent).foregroundStyle(.black)
              .disabled(store.connecting || store.address.isEmpty || store.pairingCode.isEmpty || store.deviceName.isEmpty)
          }.textFieldStyle(.roundedBorder)
        }
        if !store.message.isEmpty { Label(store.message, systemImage: "info.circle").font(.subheadline).foregroundStyle(.orange) }
        Label("No hosted SuperQode backend", systemImage: "checkmark.shield")
          .font(.caption).foregroundStyle(CompanionTheme.accent)
        Text("Keep the Mac awake and online. Public tunnel addresses are not supported. Tailscale provides the private network; your Mac approves device access.")
          .font(.caption).foregroundStyle(.secondary)
      }.padding(24)
    }.background(CompanionTheme.background).navigationTitle("SuperQode")
      .navigationBarTitleDisplayMode(.inline)
      .sheet(isPresented: $scanner) {
        NavigationStack {
          InvitationScanner { value in
            scanner = false
            if let url = URL(string: value) { store.acceptInvitation(url) }
            else { scanIssue = "This QR code is not a valid Mac invitation." }
          } failure: { message in scanner = false; scanIssue = message }
          .ignoresSafeArea(edges: .bottom).navigationTitle("Scan your Mac invitation")
          .navigationBarTitleDisplayMode(.inline)
          .toolbar { Button("Cancel") { scanner = false } }
        }
      }
  }
  private func openScanner() async {
    guard DataScannerViewController.isSupported else {
      scanIssue = "QR scanning is unavailable on this device. Enter the address and pairing code manually."
      return
    }
    let authorized = await AVCaptureDevice.requestAccess(for: .video)
    guard authorized, DataScannerViewController.isAvailable else {
      scanIssue = "Camera access is unavailable. Enter the code manually, or enable camera access in iPhone Settings."
      return
    }
    scanner = true
  }
}

private struct InvitationScanner: UIViewControllerRepresentable {
  let receive: (String) -> Void
  let failure: (String) -> Void
  func makeCoordinator() -> Coordinator { Coordinator(receive: receive) }
  func makeUIViewController(context: Context) -> DataScannerViewController {
    let scanner = DataScannerViewController(recognizedDataTypes: [.barcode(symbologies: [.qr])],
      qualityLevel: .balanced, recognizesMultipleItems: false, isHighFrameRateTrackingEnabled: false,
      isPinchToZoomEnabled: true, isGuidanceEnabled: true, isHighlightingEnabled: true)
    scanner.delegate = context.coordinator
    do { try scanner.startScanning() }
    catch { Task { @MainActor in failure("The camera could not start. Enter the pairing code manually.") } }
    return scanner
  }
  func updateUIViewController(_ controller: DataScannerViewController, context: Context) {}
  static func dismantleUIViewController(_ controller: DataScannerViewController, coordinator: Coordinator) { controller.stopScanning() }
  final class Coordinator: NSObject, DataScannerViewControllerDelegate {
    let receive: (String) -> Void
    private var completed = false
    init(receive: @escaping (String) -> Void) { self.receive = receive }
    func dataScanner(_ dataScanner: DataScannerViewController, didAdd addedItems: [RecognizedItem], allItems: [RecognizedItem]) {
      guard !completed else { return }
      for item in addedItems {
        if case .barcode(let barcode) = item, let value = barcode.payloadStringValue {
          completed = true
          dataScanner.stopScanning()
          receive(value)
          return
        }
      }
    }
  }
}
