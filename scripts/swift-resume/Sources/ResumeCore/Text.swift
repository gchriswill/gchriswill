import Foundation
import Crypto

public struct ResumeError: Error, CustomStringConvertible {
    public let description: String
    public init(_ description: String) { self.description = description }
}

func digest(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }

func isWhitespace(_ scalar: Unicode.Scalar) -> Bool {
    switch scalar.value {
    case 9...13, 28...32, 0x85, 0xa0, 0x1680, 0x2000...0x200a, 0x2028, 0x2029, 0x202f, 0x205f, 0x3000:
        return true
    default: return false
    }
}

func stripped(_ text: String) -> String {
    String(String.UnicodeScalarView(text.unicodeScalars.drop(while: isWhitespace).reversed()
        .drop(while: isWhitespace).reversed()))
}

func lines(_ text: String) -> [String] {
    let scalars = Array(text.unicodeScalars)
    var result: [String] = []
    var start = 0
    var index = 0
    while index < scalars.count {
        if [10, 13, 11, 12, 28, 29, 30, 0x85, 0x2028, 0x2029].contains(scalars[index].value) {
            result.append(String(String.UnicodeScalarView(scalars[start..<index])))
            if scalars[index].value == 13 && index + 1 < scalars.count && scalars[index + 1].value == 10 {
                index += 1
            }
            start = index + 1
        }
        index += 1
    }
    if start < scalars.count { result.append(String(String.UnicodeScalarView(scalars[start...]))) }
    return result
}

func byteLines(_ data: Data) -> [Data] {
    let bytes = Array(data)
    var result: [Data] = []
    var start = 0
    var index = 0
    while index < bytes.count {
        if bytes[index] == 10 || bytes[index] == 13 {
            if bytes[index] == 13 && index + 1 < bytes.count && bytes[index + 1] == 10 { index += 1 }
            result.append(Data(bytes[start...index]))
            start = index + 1
        }
        index += 1
    }
    if start < bytes.count { result.append(Data(bytes[start...])) }
    return result
}

func markedSection(_ lines: [Data], start: String, end: String) throws -> (Int, Int) {
    func matches(_ marker: String) -> [Int] {
        lines.indices.filter { Data(lines[$0].reversed().drop(while: { $0 == 10 || $0 == 13 }).reversed()) == Data(marker.utf8) }
    }
    let starts = matches(start), ends = matches(end)
    guard starts.count == 1, ends.count == 1, starts[0] < ends[0] else {
        throw ResumeError("Expected exactly one ordered pair of markers: \(start) / \(end)")
    }
    return (starts[0], ends[0])
}

func utf8(_ data: Data) throws -> String {
    guard let text = String(data: data, encoding: .utf8) else { throw ResumeError("Invalid UTF-8") }
    return text
}

func replace(_ pattern: String, in text: String, with replacement: String) throws -> String {
    let regex = try NSRegularExpression(pattern: pattern)
    return regex.stringByReplacingMatches(in: text, range: NSRange(text.startIndex..., in: text), withTemplate: replacement)
}

func normalizeBullets(_ text: String) throws -> String {
    // Python's MULTILINE anchors recognize LF, not ICU's other line separators.
    try text.components(separatedBy: "\n").map {
        try replace("^([ \\t]*-)[ \\t]{2,}", in: $0, with: "$1 ")
    }.joined(separator: "\n")
}

public func wrapLine(_ source: String, columns: Int) throws -> [String] {
    guard columns > 0 else { throw ResumeError("Wrapping width must be positive") }
    var expanded: [Unicode.Scalar] = []
    var column = 0
    for scalar in source.unicodeScalars {
        if scalar.value == 9 {
            let count = 4 - column % 4
            expanded += Array(repeating: Unicode.Scalar(32)!, count: count)
            column += count
        } else {
            expanded.append(scalar)
            column = scalar.value == 10 || scalar.value == 13 ? 0 : column + 1
        }
    }
    let indent = Array(expanded.prefix(while: isWhitespace))
    let normalized = expanded.map { [9, 10, 11, 12, 13].contains($0.value) ? Unicode.Scalar(32)! : $0 }
    var chunks: [[Unicode.Scalar]] = []
    for scalar in normalized {
        let whitespace = scalar.value == 32
        if let last = chunks.last, (last[0].value == 32) == whitespace {
            chunks[chunks.count - 1].append(scalar)
        } else { chunks.append([scalar]) }
    }
    chunks.reverse()
    var output: [String] = []
    while !chunks.isEmpty {
        let prefix = output.isEmpty ? [] : indent
        let width = columns - prefix.count
        var current: [[Unicode.Scalar]] = []
        var length = 0
        if let last = chunks.last, last.allSatisfy(isWhitespace), !output.isEmpty { chunks.removeLast() }
        while let chunk = chunks.last, length + chunk.count <= width {
            current.append(chunks.removeLast())
            length += chunk.count
        }
        if let chunk = chunks.last, chunk.count > width {
            let available = width < 1 ? 1 : width - length
            current.append(Array(chunk.prefix(available)))
            chunks[chunks.count - 1] = Array(chunk.dropFirst(available))
        }
        // Python drops a trailing whitespace chunk, not whitespace within a word.
        if let last = current.last, last.allSatisfy(isWhitespace) { current.removeLast() }
        if !current.isEmpty { output.append(String(String.UnicodeScalarView(prefix + current.flatMap { $0 }))) }
    }
    return output.isEmpty ? [""] : output
}
