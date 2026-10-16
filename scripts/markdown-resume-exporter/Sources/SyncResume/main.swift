import Foundation
import ResumeCore

do {
    var args = Array(CommandLine.arguments.dropFirst())
    var root: URL?
    var layout: URL?
    var font = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
    while !args.isEmpty {
        let option = args.removeFirst()
        guard !args.isEmpty else { throw ResumeError("Missing value for \(option)") }
        let value = args.removeFirst()
        switch option {
        case "--root": root = URL(fileURLWithPath: value, isDirectory: true).standardizedFileURL
        case "--layout": layout = URL(fileURLWithPath: value)
        case "--font": font = value
        default: throw ResumeError("Unknown option: \(option)")
        }
    }
    guard let root else {
        throw ResumeError("Supply --root <repository or fixture directory> [--layout <json>] [--font <ttf>]")
    }
    try synchronize(root: root, fontPath: font, layoutDestination: layout)
} catch {
    FileHandle.standardError.write(Data("sync-resume: \(error)\n".utf8))
    exit(1)
}
