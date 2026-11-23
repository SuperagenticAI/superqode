import SwiftUI

/// Original workflow marks. These are not the official Scrum, Kanban, XP, or Lean logos.
struct FactoryWorkflowMark: View {
  let id: String

  var body: some View {
    ZStack {
      RoundedRectangle(cornerRadius: 8, style: .continuous)
        .fill(tile)
      content
        .padding(5)
    }
    .accessibilityHidden(true)
  }

  private var tile: Color {
    switch id {
    case "fix-and-verify": Color(red: 0.98, green: 0.93, blue: 0.84)
    case "continuous-outcomes": Color(red: 0.88, green: 0.93, blue: 0.98)
    case "build-test-deploy": Color(red: 0.88, green: 0.95, blue: 0.91)
    case "kanban": Color(red: 0.93, green: 0.94, blue: 0.96)
    case "scrum": Color(red: 0.86, green: 0.95, blue: 0.92)
    case "xp": Color(red: 0.98, green: 0.92, blue: 0.90)
    case "lean": Color(red: 0.98, green: 0.95, blue: 0.86)
    default: Color.primary.opacity(0.06)
    }
  }

  @ViewBuilder private var content: some View {
    switch id {
    case "fix-and-verify": fixMark
    case "continuous-outcomes": continuousMark
    case "build-test-deploy": pipelineMark
    case "kanban": kanbanMark
    case "scrum": scrumMark
    case "xp": xpMark
    case "lean": leanMark
    default: EmptyView()
    }
  }

  private var fixMark: some View {
    ZStack(alignment: .bottomTrailing) {
      Circle()
        .stroke(Color(red: 0.78, green: 0.42, blue: 0.12), lineWidth: 2.2)
        .padding(3)
      Circle()
        .trim(from: 0.55, to: 0.72)
        .stroke(Color(red: 0.78, green: 0.42, blue: 0.12), style: StrokeStyle(lineWidth: 2.2, lineCap: .round))
        .rotationEffect(.degrees(40))
        .padding(1)
      Image(systemName: "checkmark")
        .font(.system(size: 8, weight: .bold))
        .foregroundStyle(.white)
        .padding(2)
        .background(Color(red: 0.18, green: 0.55, blue: 0.32), in: Circle())
    }
  }

  private var continuousMark: some View {
    ZStack {
      Circle()
        .trim(from: 0.08, to: 0.62)
        .stroke(Color(red: 0.18, green: 0.42, blue: 0.72), style: StrokeStyle(lineWidth: 2.2, lineCap: .round))
        .rotationEffect(.degrees(-20))
      Circle()
        .trim(from: 0.08, to: 0.62)
        .stroke(Color(red: 0.16, green: 0.58, blue: 0.62), style: StrokeStyle(lineWidth: 2.2, lineCap: .round))
        .rotationEffect(.degrees(160))
      Circle().fill(Color(red: 0.18, green: 0.42, blue: 0.72)).frame(width: 4, height: 4).offset(x: 7, y: -5)
      Circle().fill(Color(red: 0.16, green: 0.58, blue: 0.62)).frame(width: 4, height: 4).offset(x: -7, y: 5)
    }
    .padding(2)
  }

  private var pipelineMark: some View {
    HStack(spacing: 2) {
      RoundedRectangle(cornerRadius: 2).fill(Color(red: 0.18, green: 0.42, blue: 0.72))
      Capsule().fill(Color(red: 0.55, green: 0.62, blue: 0.68)).frame(width: 5, height: 2)
      Circle().fill(Color(red: 0.86, green: 0.55, blue: 0.16))
      Capsule().fill(Color(red: 0.55, green: 0.62, blue: 0.68)).frame(width: 5, height: 2)
      Image(systemName: "arrowtriangle.right.fill")
        .font(.system(size: 8))
        .foregroundStyle(Color(red: 0.16, green: 0.52, blue: 0.34))
    }
  }

  private var kanbanMark: some View {
    HStack(spacing: 2) {
      kanbanColumn(Color(red: 0.45, green: 0.52, blue: 0.58), heights: [9, 6])
      kanbanColumn(Color(red: 0.16, green: 0.42, blue: 0.72), heights: [11])
      kanbanColumn(Color(red: 0.16, green: 0.52, blue: 0.36), heights: [7, 4])
    }
  }

  private func kanbanColumn(_ color: Color, heights: [CGFloat]) -> some View {
    VStack(spacing: 1.5) {
      Capsule().fill(color).frame(height: 2.5)
      ForEach(Array(heights.enumerated()), id: \.offset) { _, height in
        RoundedRectangle(cornerRadius: 1.5).fill(color.opacity(0.9)).frame(height: height)
      }
      Spacer(minLength: 0)
    }
  }

  private var scrumMark: some View {
    ZStack {
      Circle()
        .trim(from: 0.12, to: 0.88)
        .stroke(Color(red: 0.12, green: 0.50, blue: 0.42), style: StrokeStyle(lineWidth: 2.3, lineCap: .round))
        .rotationEffect(.degrees(-70))
      Image(systemName: "arrowtriangle.right.fill")
        .font(.system(size: 6))
        .foregroundStyle(Color(red: 0.12, green: 0.50, blue: 0.42))
        .offset(x: 8, y: -1)
      Circle().fill(Color(red: 0.90, green: 0.58, blue: 0.16)).frame(width: 4, height: 4).offset(y: -7)
      Circle().fill(Color(red: 0.18, green: 0.42, blue: 0.72)).frame(width: 4, height: 4).offset(x: -6, y: 5)
      Circle().fill(Color(red: 0.16, green: 0.52, blue: 0.36)).frame(width: 4, height: 4).offset(x: 6, y: 5)
    }
    .padding(1)
  }

  private var xpMark: some View {
    HStack(spacing: 3) {
      ZStack {
        Circle().fill(Color(red: 0.75, green: 0.24, blue: 0.22))
        Capsule().fill(.white).frame(width: 7, height: 1.6)
      }
      Image(systemName: "arrow.right")
        .font(.system(size: 7, weight: .bold))
        .foregroundStyle(Color(red: 0.45, green: 0.38, blue: 0.32))
      ZStack {
        Circle().fill(Color(red: 0.16, green: 0.52, blue: 0.34))
        Image(systemName: "checkmark")
          .font(.system(size: 7, weight: .bold))
          .foregroundStyle(.white)
      }
    }
  }

  private var leanMark: some View {
    HStack(spacing: 2) {
      VStack(spacing: 1.5) {
        RoundedRectangle(cornerRadius: 1).fill(Color(red: 0.72, green: 0.48, blue: 0.14)).frame(height: 7)
        RoundedRectangle(cornerRadius: 1).fill(Color(red: 0.72, green: 0.48, blue: 0.14).opacity(0.75)).frame(width: 8, height: 5)
        RoundedRectangle(cornerRadius: 1).fill(Color(red: 0.72, green: 0.48, blue: 0.14).opacity(0.5)).frame(width: 5, height: 3)
      }
      Image(systemName: "arrowtriangle.right.fill")
        .font(.system(size: 9))
        .foregroundStyle(Color(red: 0.55, green: 0.34, blue: 0.08))
    }
  }
}
