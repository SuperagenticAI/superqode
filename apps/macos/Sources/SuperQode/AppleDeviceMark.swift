import SwiftUI

/// A whole apple with a stem and a leaf.
/// This is an original fruit mark so the Apple on-device route is recognizable.
/// It is not Apple's logo.
struct AppleDeviceMark: Shape {
  func path(in rect: CGRect) -> Path {
    let x = rect.minX
    let y = rect.minY
    let w = rect.width
    let h = rect.height
    func p(_ px: CGFloat, _ py: CGFloat) -> CGPoint {
      CGPoint(x: x + w * px, y: y + h * py)
    }
    var path = Path()
    path.move(to: p(0.50, 0.30))
    path.addCurve(to: p(0.16, 0.56), control1: p(0.30, 0.26), control2: p(0.14, 0.38))
    path.addCurve(to: p(0.50, 0.94), control1: p(0.18, 0.80), control2: p(0.30, 0.94))
    path.addCurve(to: p(0.84, 0.56), control1: p(0.70, 0.94), control2: p(0.82, 0.80))
    path.addCurve(to: p(0.50, 0.30), control1: p(0.86, 0.38), control2: p(0.70, 0.26))
    path.closeSubpath()
    path.move(to: p(0.48, 0.30))
    path.addQuadCurve(to: p(0.56, 0.11), control: p(0.45, 0.16))
    path.addQuadCurve(to: p(0.50, 0.30), control: p(0.62, 0.18))
    path.closeSubpath()
    path.move(to: p(0.54, 0.18))
    path.addQuadCurve(to: p(0.88, 0.07), control: p(0.72, 0.01))
    path.addQuadCurve(to: p(0.54, 0.18), control: p(0.76, 0.20))
    path.closeSubpath()
    return path
  }
}
