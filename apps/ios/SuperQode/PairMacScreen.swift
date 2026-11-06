import AVFoundation
import SwiftUI
import VisionKit

struct PairMacScreen: View {
  @EnvironmentObject private var store: CompanionStore
  @State private var scanner = false
  @State private var scanIssue = ""
  @State private var manual = false
  private var invitationReady: Bool { !store.pairingCode.isEmpty && !store.address.isEmpty }
  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 24) {
        VStack(alignment: .leading, spacing: 16) {
          SuperQodeMark(size: 72).padding(.top, 12)
          Text("Your Mac. Your models.\nA little more freedom.")
            .font(.system(.largeTitle, design: .rounded, weight: .bold))
          Text("Code, review and evaluate from your iPhone. Everything runs on the Mac you already own.")
            .font(.subheadline).foregroundStyle(.secondary)
        }
        if store.waitingForApproval {
          approvalWaiting
        } else {
          CompanionCard {
            Label("Connect your workspace", systemImage: "lock.shield").font(.headline)
            Text("On your Mac, open SuperQode Settings → Private remote access and create an invitation.")
              .font(.subheadline).foregroundStyle(.secondary)
            if invitationReady {
              Label("Invitation ready", systemImage: "checkmark.circle.fill").foregroundStyle(CompanionTheme.accent)
              Text(store.address).font(.caption.monospaced()).textSelection(.enabled)
              TextField("Name this iPhone", text: $store.deviceName).textFieldStyle(.roundedBorder)
              Button { store.beginPairing() } label: { HStack { if store.connecting { ProgressView().tint(.white) }; Text(store.connecting ? "Connecting…" : "Request Mac approval") } }
                .buttonStyle(CompanionPrimaryButton()).disabled(store.connecting || store.deviceName.trimmingCharacters(in: .whitespaces).isEmpty)
            } else {
              Button { Task { await openScanner() } } label: { Label("Scan Mac invitation", systemImage: "qrcode.viewfinder") }
                .buttonStyle(CompanionPrimaryButton()).disabled(store.connecting)
            }
            DisclosureGroup("Enter an invitation manually", isExpanded: $manual) {
              VStack(alignment: .leading, spacing: 12) {
                TextField("https://your-mac.tailnet.ts.net:47832", text: $store.address)
                  .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                  .accessibilityLabel("Private Mac address")
                SecureField("Pairing invitation code", text: $store.pairingCode)
                  .textInputAutocapitalization(.never).autocorrectionDisabled()
                  .accessibilityLabel("Pairing invitation code")
                Text("Copy the exact address and five-minute code shown by your Mac. The address includes a port number.")
                  .font(.caption).foregroundStyle(.secondary)
              }.textFieldStyle(.roundedBorder).padding(.top, 8).disabled(store.connecting)
            }.font(.subheadline)
            if !scanIssue.isEmpty { Text(scanIssue).font(.caption).foregroundStyle(CompanionTheme.warning) }
          }
        }
        if !store.message.isEmpty {
          Label(store.message, systemImage: "info.circle").font(.subheadline).foregroundStyle(.secondary)
        }
        Button { store.enterExploreMode() } label: { Label("Explore the app with sample data", systemImage: "eye") }.font(.subheadline)
          .disabled(store.connecting)
        VStack(alignment: .leading, spacing: 14) {
          setupStep("1", "Your private connection", "Install Tailscale on your Mac and iPhone and sign in to your own private network.")
          setupStep("2", "You approve access", "Pair once and approve the phone on your Mac. Share only the workspaces and connections you choose.")
          setupStep("3", "Pick up from anywhere", "Leave the Mac awake and online. Open the companion from mobile data or another Wi-Fi network.")
        }
        NavigationLink { CompanionSetupGuide() } label: { Label("Setup guide and account help", systemImage: "questionmark.circle") }.font(.subheadline)
        Label("No hosted SuperQode backend", systemImage: "checkmark.shield")
          .font(.caption).foregroundStyle(CompanionTheme.accent)
      }.padding(24).frame(maxWidth: 620).frame(maxWidth: .infinity)
    }.background(CompanionTheme.background).navigationTitle("SuperQode").companionNavigationBrand()
      .scrollDismissesKeyboard(.interactively)
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
  private var approvalWaiting: some View {
    CompanionCard {
      HStack(spacing: 12) { ProgressView(); Text("One last approval on your Mac").font(.headline) }
      Text("Check the Tailscale identity and phone name in Private remote access, then choose Approve. Keep this screen open while your Mac responds.")
        .font(.subheadline).foregroundStyle(.secondary)
      Button("Cancel pairing") { store.cancelPairing() }
    }
  }
  private func setupStep(_ number: String, _ title: String, _ description: String) -> some View {
    HStack(alignment: .top, spacing: 12) {
      Text(number).font(.caption.bold()).foregroundStyle(CompanionTheme.accent)
        .frame(width: 24, height: 24).background(CompanionTheme.accent.opacity(0.1), in: Circle())
      VStack(alignment: .leading, spacing: 4) { Text(title).font(.subheadline.weight(.semibold)); Text(description).font(.caption).foregroundStyle(.secondary) }
    }
  }
  private func openScanner() async {
    guard DataScannerViewController.isSupported else {
      scanIssue = "QR scanning is unavailable on this device. Enter the address and pairing code manually."
      manual = true
      return
    }
    let authorized = await AVCaptureDevice.requestAccess(for: .video)
    guard authorized, DataScannerViewController.isAvailable else {
      scanIssue = "Camera access is unavailable. Use manual pairing, or enable camera access in iPhone Settings."
      manual = true
      return
    }
    scanner = true
  }
}

struct CompanionSetupGuide: View {
  var body: some View {
    List {
      Section {
        SuperQodeWordmark().padding(.vertical, 12)
        Text("Two devices. One workspace.").font(.title2.bold())
        Text("Your Mac runs SuperQode and your models. Your phone connects privately to control the same jobs. You do not need to host a SuperQode server.")
      }
      Section("On the Mac") {
        Text("Use a Mac build that includes Private remote access. Open a project, configure its connection, enable the background engine and share the connection with your phone.")
        Text("Install Tailscale and use Configure private Serve in SuperQode. Keep the Mac awake, online and signed in; closing the lid can make it unavailable.")
        Link("Get Tailscale", destination: URL(string: "https://tailscale.com/download")!)
      }
      Section("On this iPhone") {
        Text("Sign in to the same private Tailscale network. Scan the invitation from your Mac, request access, then approve it on the Mac. Camera permission is only requested when you tap Scan.")
        Text("If an invitation expires or a camera is unavailable, enter a fresh invitation manually. A new conversation always asks you to choose a connection.")
      }
      Section("Accounts and credentials") {
        Text("Use your Tailscale account in the Tailscale app. Personal noncommercial use can qualify for its free plan; business use follows Tailscale's terms.")
        Link("Tailscale plans", destination: URL(string: "https://tailscale.com/pricing")!)
        Text("Model and agent credentials stay configured on the Mac. The companion stores its own device authorization in this iPhone's Keychain.")
        Text("For source builds, add your Apple Developer account in Xcode Settings → Accounts and select your team under Signing & Capabilities. No Apple password or private signing key belongs in the source code.")
      }
      Section("Privacy") {
        Text("Tailscale supplies private networking and may relay encrypted traffic. SuperQode has no hosted relay. Cloud agents can still contact their own providers; choose a verified Local only connection when you want local inference.")
        Text("Phone access can be revoked on the Mac. Unsent drafts are protected on this iPhone and excluded from backups. Work continues on the Mac when the phone app closes; live updates resume when you reopen it.")
      }
    }.navigationTitle("Get started").navigationBarTitleDisplayMode(.inline)
      .scrollContentBackground(.hidden).background(CompanionTheme.background)
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
