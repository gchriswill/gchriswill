import Foundation

indirect enum JSONValue: Codable {
    case object([String: JSONValue]), array([JSONValue]), string(String), number(Double), bool(Bool), null

    init(from decoder: any Decoder) throws {
        let value = try decoder.singleValueContainer()
        if value.decodeNil() { self = .null }
        else if let v = try? value.decode(Bool.self) { self = .bool(v) }
        else if let v = try? value.decode(Double.self) { self = .number(v) }
        else if let v = try? value.decode(String.self) { self = .string(v) }
        else if let v = try? value.decode([JSONValue].self) { self = .array(v) }
        else { self = .object(try value.decode([String: JSONValue].self)) }
    }

    func encode(to encoder: any Encoder) throws {
        var value = encoder.singleValueContainer()
        switch self {
        case .object(let v): try value.encode(v)
        case .array(let v): try value.encode(v)
        case .string(let v): try value.encode(v)
        case .number(let v): try value.encode(v)
        case .bool(let v): try value.encode(v)
        case .null: try value.encodeNil()
        }
    }

    var object: [String: JSONValue]? { if case .object(let v) = self { v } else { nil } }
    var array: [JSONValue]? { if case .array(let v) = self { v } else { nil } }
    var string: String? { if case .string(let v) = self { v } else { nil } }
}

func preserveLinks(_ node: JSONValue) throws -> JSONValue {
    switch node {
    case .array(let values): return .array(try values.map(preserveLinks))
    case .object(let values):
        if values["t"]?.string == "Link" {
            guard let contents = values["c"]?.array, contents.count == 3,
                  let label = try preserveLinks(contents[1]).array,
                  let url = contents[2].array?.first?.string else { throw ResumeError("Invalid Pandoc Link") }
            return .object(["t": .string("Span"), "c": .array([
                contents[0], .array(label + [.object(["t": .string("Space")]),
                    .object(["t": .string("Str"), "c": .string("(\(url))")])])
            ])])
        }
        return .object(try values.mapValues(preserveLinks))
    default: return node
    }
}

struct HeadingSpacing {
    let start: String
    let end: String
    let before: Int
    let after: Int
}

func markHeadings(_ markdown: String, document: inout JSONValue) throws -> [HeadingSpacing] {
    let source = lines(markdown)
    let fencePattern = try NSRegularExpression(pattern: "^ {0,3}(`{3,}|~{3,})(.*)$")
    let headingPattern = try NSRegularExpression(pattern: "^ {0,3}(#{1,6})(?:[ \\t]+|$)")
    func captures(_ regex: NSRegularExpression, _ line: String) -> [String]? {
        guard let match = regex.firstMatch(in: line, range: NSRange(line.startIndex..., in: line)) else { return nil }
        return (1..<match.numberOfRanges).map { String(line[Range(match.range(at: $0), in: line)!]) }
    }
    var fence: String?
    var headings: [(Int, Int, Int)] = []
    for (index, line) in source.enumerated() {
        let fenced = captures(fencePattern, line)
        if let open = fence {
            if let fenced, fenced[0].first == open.first, fenced[0].count >= open.count, stripped(fenced[1]).isEmpty {
                fence = nil
            }
            continue
        }
        if let fenced { fence = fenced[0]; continue }
        if let heading = captures(headingPattern, line) {
            var before = index, after = index + 1
            while before > 0 && stripped(source[before - 1]).isEmpty { before -= 1 }
            while after < source.count && stripped(source[after]).isEmpty { after += 1 }
            headings.append((heading[0].count, index - before + (before > 0 ? 1 : 0),
                after - index - (after == source.count ? 1 : 0)))
        }
    }
    guard var object = document.object, var blocks = object["blocks"]?.array else { throw ResumeError("Invalid Pandoc document") }
    let indices = blocks.indices.filter { blocks[$0].object?["t"]?.string == "Header" }
    let levels = indices.map { blocks[$0].object?["c"]?.array?.first }
    guard levels.count == headings.count, zip(levels, headings).allSatisfy({
        if case .number(let value) = $0.0 { return value == Double($0.1.0) }
        return false
    }) else { throw ResumeError("Resume headings must be top-level ATX (#) headings.") }
    let token = "RESUMEHEADING" + digest(Data(markdown.utf8))
    guard !markdown.contains(token) else { throw ResumeError("Resume content conflicts with heading spacing markers.") }
    var spacing: [HeadingSpacing] = []
    for (offset, index) in indices.enumerated() {
        guard var header = blocks[index].object, var contents = header["c"]?.array, contents.count == 3,
              let inlines = contents[2].array else { throw ResumeError("Invalid Pandoc Header") }
        let start = "\(token)\(offset)START", end = "\(token)\(offset)END"
        contents[2] = .array([.object(["t": .string("Str"), "c": .string(start)])] + inlines
            + [.object(["t": .string("Str"), "c": .string(end)])])
        header["c"] = .array(contents)
        blocks[index] = .object(header)
        spacing.append(HeadingSpacing(start: start, end: end, before: headings[offset].1, after: headings[offset].2))
    }
    object["blocks"] = .array(blocks)
    document = .object(object)
    return spacing
}

func restoreHeadings(_ input: String, spacing: [HeadingSpacing]) throws -> String {
    var text = input
    for item in spacing {
        guard text.components(separatedBy: item.start).count == 2,
              text.components(separatedBy: item.end).count == 2 else {
            throw ResumeError("Pandoc did not preserve heading spacing markers.")
        }
        text = try replace("[ \\t]*(?:\\n[ \\t]*)*" + NSRegularExpression.escapedPattern(for: item.start),
            in: text, with: String(repeating: "\n", count: item.before))
        text = try replace(NSRegularExpression.escapedPattern(for: item.end) + "(?:[ \\t]*\\n)*",
            in: text, with: String(repeating: "\n", count: item.after))
    }
    return text
}

struct Pandoc {
    let scratch: URL
    let executable: URL

    init(root: URL) throws {
        guard let path = ProcessInfo.processInfo.environment["PATH"]?.components(separatedBy: ":")
            .map({ URL(fileURLWithPath: $0).appendingPathComponent("pandoc") })
            .first(where: { FileManager.default.isExecutableFile(atPath: $0.path) }) else {
            throw ResumeError("pandoc was not found on PATH")
        }
        executable = path
        scratch = root.appendingPathComponent(".sync-resume-work-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: scratch, withIntermediateDirectories: false)
    }

    func run(_ arguments: [String], input: Data) throws -> Data {
        let inputURL = scratch.appendingPathComponent("stdin")
        let outputURL = scratch.appendingPathComponent("stdout")
        let errorURL = scratch.appendingPathComponent("stderr")
        try input.write(to: inputURL)
        try Data().write(to: outputURL)
        try Data().write(to: errorURL)
        let stdin = try FileHandle(forReadingFrom: inputURL)
        let stdout = try FileHandle(forWritingTo: outputURL)
        let stderr = try FileHandle(forWritingTo: errorURL)
        defer { stdin.closeFile(); stdout.closeFile(); stderr.closeFile() }
        let process = Process()
        process.executableURL = executable
        process.arguments = arguments
        process.standardInput = stdin
        process.standardOutput = stdout
        process.standardError = stderr
        try process.run()
        process.waitUntilExit()
        guard process.terminationReason == .exit, process.terminationStatus == 0 else {
            throw ResumeError("pandoc failed (\(process.terminationStatus)): \(try utf8(Data(contentsOf: errorURL)))")
        }
        // subprocess.run(text=True) uses universal-newline decoding.
        let text = try utf8(Data(contentsOf: outputURL)).replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")
        return Data(text.utf8)
    }

    func removeScratch() throws { try FileManager.default.removeItem(at: scratch) }
}
