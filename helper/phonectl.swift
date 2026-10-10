// phonectl: see and touch the iPhone Mirroring window from the command line.
//
// Every command prints one JSON object on stdout. Errors print {"error": ...}
// and exit 1. Positions are fractions of the mirroring window: (0, 0) is the
// top-left corner, (1, 1) the bottom-right.
//
//   phonectl doctor [--request]         permissions and window status
//   phonectl shot <out.png> [--ocr] [--fast]
//   phonectl ocr-file <in.png> [--fast] OCR a saved image (no phone needed)
//   phonectl tap <x> <y>
//   phonectl drag <x1> <y1> <x2> <y2> [ms] [hold_ms]
//   phonectl scroll <x> <y> <dx> <dy>   wheel scroll, in pixels
//
// Capturing needs the Screen Recording permission and input needs the
// Accessibility permission, both for the app that launches this binary.

import AppKit
import ApplicationServices
import CoreGraphics
import Foundation
import ImageIO
import ScreenCaptureKit
import UniformTypeIdentifiers
import Vision

let mirroringBundleID = "com.apple.ScreenContinuity"

struct Fail: Error {
    let msg: String
    init(_ msg: String) { self.msg = msg }
}

struct Win {
    let id: CGWindowID
    let pid: pid_t
    let frame: CGRect  // screen points, origin at the top-left of the main display

    var json: [String: Any] {
        ["id": Int(id), "x": Double(frame.minX), "y": Double(frame.minY),
         "w": Double(frame.width), "h": Double(frame.height)]
    }

    func point(_ fx: Double, _ fy: Double) -> CGPoint {
        CGPoint(x: frame.minX + CGFloat(fx) * frame.width, y: frame.minY + CGFloat(fy) * frame.height)
    }
}

func emit(_ obj: [String: Any]) {
    let data = (try? JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys])) ?? Data("{}".utf8)
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
}

func ms(since t0: Date) -> Double {
    (Date().timeIntervalSince(t0) * 10000).rounded() / 10
}

// MARK: windows

/// Ordinary app windows currently on screen, front to back.
func appWindows() -> [Win] {
    let opts: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
    guard let list = CGWindowListCopyWindowInfo(opts, kCGNullWindowID) as? [[String: Any]] else { return [] }
    var out: [Win] = []
    for w in list {
        guard let layer = w[kCGWindowLayer as String] as? NSNumber, layer.intValue == 0,
              let pid = w[kCGWindowOwnerPID as String] as? NSNumber,
              let num = w[kCGWindowNumber as String] as? NSNumber,
              let bounds = w[kCGWindowBounds as String] as? NSDictionary,
              let rect = CGRect(dictionaryRepresentation: bounds as CFDictionary) else { continue }
        if let alpha = w[kCGWindowAlpha as String] as? NSNumber, alpha.doubleValue <= 0 { continue }
        if rect.width < 50 || rect.height < 50 { continue }
        out.append(Win(id: CGWindowID(num.uint32Value), pid: pid.int32Value, frame: rect))
    }
    return out
}

func mirroringPid() -> pid_t? {
    NSRunningApplication.runningApplications(withBundleIdentifier: mirroringBundleID).first?.processIdentifier
}

func findWindow() throws -> Win {
    guard let pid = mirroringPid() else { throw Fail("iPhone Mirroring is not running") }
    let mine = appWindows().filter { $0.pid == pid }
    guard let win = mine.max(by: { $0.frame.width * $0.frame.height < $1.frame.width * $1.frame.height }) else {
        throw Fail("iPhone Mirroring has no visible window (minimised, or on another Space?)")
    }
    return win
}

func isFrontmost(_ win: Win) -> Bool {
    appWindows().first?.pid == win.pid
}

func bringToFront(_ win: Win) -> Bool {
    if isFrontmost(win) { return true }
    NSRunningApplication(processIdentifier: win.pid)?.activate(options: [.activateAllWindows])
    for _ in 0..<8 {
        usleep(50_000)
        if isFrontmost(win) { return true }
    }
    let app = AXUIElementCreateApplication(win.pid)
    AXUIElementSetAttributeValue(app, kAXFrontmostAttribute as CFString, kCFBooleanTrue)
    for _ in 0..<8 {
        usleep(50_000)
        if isFrontmost(win) { return true }
    }
    return false
}

/// Refuse to send input unless the mirroring window is what the pointer would hit.
func requireClear(_ win: Win, at points: [CGPoint]) throws {
    guard AXIsProcessTrusted() else {
        throw Fail("no Accessibility permission, so input would be dropped (run: phonectl doctor --request)")
    }
    guard bringToFront(win) else { throw Fail("could not bring iPhone Mirroring to the front") }
    let windows = appWindows()
    for p in points {
        guard win.frame.contains(p) else { throw Fail("point is outside the mirroring window") }
        if let top = windows.first(where: { $0.frame.contains(p) }), top.id != win.id {
            throw Fail("another window covers the mirroring window at that point")
        }
    }
}

// MARK: capture and OCR

func capture(_ win: Win) async throws -> CGImage {
    guard CGPreflightScreenCaptureAccess() else {
        throw Fail("no Screen Recording permission (run: phonectl doctor --request)")
    }
    let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
    guard let target = content.windows.first(where: { $0.windowID == win.id }) else {
        throw Fail("the mirroring window is not available for capture")
    }
    let filter = SCContentFilter(desktopIndependentWindow: target)
    let scale = CGFloat(filter.pointPixelScale)
    let cfg = SCStreamConfiguration()
    cfg.width = Int((filter.contentRect.width * scale).rounded())
    cfg.height = Int((filter.contentRect.height * scale).rounded())
    cfg.showsCursor = false
    cfg.ignoreShadowsSingleWindow = true
    return try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: cfg)
}

func writePNG(_ image: CGImage, to path: String) throws {
    let url = URL(fileURLWithPath: path)
    guard let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil) else {
        throw Fail("cannot write \(path)")
    }
    CGImageDestinationAddImage(dest, image, nil)
    guard CGImageDestinationFinalize(dest) else { throw Fail("cannot write \(path)") }
}

func readImage(_ path: String) throws -> CGImage {
    let url = URL(fileURLWithPath: path)
    guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(src, 0, nil) else {
        throw Fail("cannot read image \(path)")
    }
    return image
}

func round4(_ v: CGFloat) -> Double {
    (Double(v) * 10000).rounded() / 10000
}

/// Text found in the image, with boxes as fractions of the image (origin top-left).
func recognise(_ image: CGImage, fast: Bool) throws -> [[String: Any]] {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = fast ? .fast : .accurate
    request.usesLanguageCorrection = false
    try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
    var out: [[String: Any]] = []
    for obs in request.results ?? [] {
        guard let best = obs.topCandidates(1).first else { continue }
        let box = obs.boundingBox  // origin bottom-left
        out.append([
            "text": best.string, "conf": round4(CGFloat(best.confidence)),
            "x": round4(box.minX), "y": round4(1 - box.maxY), "w": round4(box.width), "h": round4(box.height),
        ])
    }
    return out
}

// MARK: input

let eventSource = CGEventSource(stateID: .hidSystemState)

func mouse(_ type: CGEventType, _ p: CGPoint, dx: Int64 = 0, dy: Int64 = 0) {
    guard let event = CGEvent(mouseEventSource: eventSource, mouseType: type,
                              mouseCursorPosition: p, mouseButton: .left) else { return }
    if type == .leftMouseDown || type == .leftMouseUp {
        event.setIntegerValueField(.mouseEventClickState, value: 1)
    }
    event.setIntegerValueField(.mouseEventDeltaX, value: dx)
    event.setIntegerValueField(.mouseEventDeltaY, value: dy)
    event.post(tap: .cghidEventTap)
}

func tap(_ p: CGPoint) {
    mouse(.mouseMoved, p)
    usleep(40_000)
    mouse(.leftMouseDown, p)
    usleep(60_000)
    mouse(.leftMouseUp, p)
}

/// Press at `a`, move to `b` over `duration` ms, release while still moving.
func drag(from a: CGPoint, to b: CGPoint, duration: Int, hold: Int) {
    mouse(.mouseMoved, a)
    usleep(40_000)
    mouse(.leftMouseDown, a)
    usleep(useconds_t(max(hold, 0) * 1000))
    let steps = max(2, duration / 8)
    let pause = useconds_t(max(duration, 1) * 1000 / steps)
    var prev = a
    for i in 1...steps {
        let t = CGFloat(i) / CGFloat(steps)
        let p = CGPoint(x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t)
        mouse(.leftMouseDragged, p,
              dx: Int64(p.x.rounded() - prev.x.rounded()), dy: Int64(p.y.rounded() - prev.y.rounded()))
        prev = p
        usleep(pause)
    }
    mouse(.leftMouseUp, b)
}

func scroll(at p: CGPoint, dx: Int32, dy: Int32) {
    mouse(.mouseMoved, p)
    usleep(40_000)
    let event = CGEvent(scrollWheelEvent2Source: eventSource, units: .pixel,
                        wheelCount: 2, wheel1: dy, wheel2: dx, wheel3: 0)
    event?.post(tap: .cghidEventTap)
}

// MARK: commands

let usage = "usage: phonectl doctor [--request] | shot <out.png> [--ocr] [--fast] | ocr-file <in.png> [--fast]"
    + " | tap <x> <y> | drag <x1> <y1> <x2> <y2> [ms] [hold_ms] | scroll <x> <y> <dx> <dy>"

func fraction(_ args: [String], _ i: Int) throws -> Double {
    guard i < args.count, let v = Double(args[i]), v >= 0, v <= 1 else {
        throw Fail("expected a position between 0 and 1 at argument \(i + 1)")
    }
    return v
}

func integer(_ args: [String], _ i: Int, default fallback: Int? = nil) throws -> Int {
    if i < args.count, let v = Int(args[i]) { return v }
    if i >= args.count, let fallback { return fallback }
    throw Fail("expected a whole number at argument \(i + 1)")
}

func run(_ argv: [String]) async throws {
    guard let command = argv.first else { throw Fail(usage) }
    let flags = Set(argv.filter { $0.hasPrefix("--") })
    let args = Array(argv.dropFirst()).filter { !$0.hasPrefix("--") }

    switch command {
    case "doctor":
        if flags.contains("--request") {
            _ = CGRequestScreenCaptureAccess()
            let prompt = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
            _ = AXIsProcessTrustedWithOptions(prompt)
        }
        var report: [String: Any] = [
            "screen_recording": CGPreflightScreenCaptureAccess(),
            "accessibility": AXIsProcessTrusted(),
            "mirroring_running": mirroringPid() != nil,
        ]
        if let win = try? findWindow() {
            report["window"] = win.json
            report["frontmost"] = isFrontmost(win)
        }
        emit(report)

    case "shot":
        guard let path = args.first else { throw Fail(usage) }
        let win = try findWindow()
        var t0 = Date()
        let image = try await capture(win)
        var report: [String: Any] = [
            "path": path, "px_w": image.width, "px_h": image.height,
            "window": win.json, "capture_ms": ms(since: t0),
        ]
        try writePNG(image, to: path)
        if flags.contains("--ocr") {
            t0 = Date()
            report["text"] = try recognise(image, fast: flags.contains("--fast"))
            report["ocr_ms"] = ms(since: t0)
        }
        emit(report)

    case "ocr-file":
        guard let path = args.first else { throw Fail(usage) }
        let image = try readImage(path)
        let t0 = Date()
        let text = try recognise(image, fast: flags.contains("--fast"))
        emit(["path": path, "px_w": image.width, "px_h": image.height, "text": text, "ocr_ms": ms(since: t0)])

    case "tap":
        let win = try findWindow()
        let p = win.point(try fraction(args, 0), try fraction(args, 1))
        try requireClear(win, at: [p])
        tap(p)
        emit(["ok": true, "x": Double(p.x), "y": Double(p.y)])

    case "drag":
        let win = try findWindow()
        let a = win.point(try fraction(args, 0), try fraction(args, 1))
        let b = win.point(try fraction(args, 2), try fraction(args, 3))
        let duration = try integer(args, 4, default: 300)
        let hold = try integer(args, 5, default: 60)
        try requireClear(win, at: [a, b])
        drag(from: a, to: b, duration: duration, hold: hold)
        emit(["ok": true, "ms": duration, "hold_ms": hold])

    case "scroll":
        let win = try findWindow()
        let p = win.point(try fraction(args, 0), try fraction(args, 1))
        let dx = try integer(args, 2)
        let dy = try integer(args, 3)
        try requireClear(win, at: [p])
        scroll(at: p, dx: Int32(dx), dy: Int32(dy))
        emit(["ok": true])

    default:
        throw Fail(usage)
    }
}

@main
struct PhoneCtl {
    static func main() async {
        do {
            try await run(Array(CommandLine.arguments.dropFirst()))
        } catch let failure as Fail {
            emit(["error": failure.msg])
            exit(1)
        } catch {
            emit(["error": error.localizedDescription])
            exit(1)
        }
    }
}
