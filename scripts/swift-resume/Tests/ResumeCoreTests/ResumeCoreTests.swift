import Foundation
import XCTest
@testable import ResumeCore

final class ResumeCoreTests: XCTestCase {
    func testDigestAndByteLines() throws {
        XCTAssertEqual(digest(Data("abc".utf8)), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        XCTAssertEqual(byteLines(Data("a\r\nb\rc\n".utf8)), ["a\r\n", "b\r", "c\n"].map { Data($0.utf8) })
        XCTAssertEqual(lines("a\r\nb\u{85}c\u{2028}"), ["a", "b", "c"])
        XCTAssertThrowsError(try utf8(Data([0xff])))
    }

    func testMarkers() throws {
        XCTAssertThrowsError(try markedSection([Data("end".utf8), Data("start".utf8)], start: "start", end: "end"))
        XCTAssertThrowsError(try markedSection(["start", "start", "end"].map { Data($0.utf8) }, start: "start", end: "end"))
    }

    func testWrapping() throws {
        XCTAssertEqual(try wrapLine("  alpha beta gamma", columns: 10), ["  alpha", "  beta", "  gamma"])
        XCTAssertEqual(try wrapLine("a\tb", columns: 10), ["a   b"])
        XCTAssertEqual(try wrapLine("abcdefghijkl", columns: 5), ["abcde", "fghij", "kl"])
        XCTAssertEqual(try wrapLine("a-b-c-d-e", columns: 5), ["a-b-c", "-d-e"])
        XCTAssertEqual(try wrapLine("a\u{301}bc", columns: 2), ["a\u{301}", "bc"])
        XCTAssertEqual(try wrapLine("", columns: 5), [""])
        XCTAssertThrowsError(try wrapLine("a", columns: 0))
    }

    func testBulletAnchors() throws {
        XCTAssertEqual(try normalizeBullets("prefix\u{85}-   unchanged\n-   normalized"),
            "prefix\u{85}-   unchanged\n- normalized")
        XCTAssertEqual(try normalizeBullets("-\t\tbullet\n \t-   nested"), "- bullet\n \t- nested")
    }

    func testHeadingRestorationAndFailures() throws {
        var document = JSONValue.object(["blocks": .array([
            .object(["t": .string("Header"), "c": .array([.number(1), .array([]), .array([.object(["t": .string("Str"), "c": .string("Title")])])])])
        ])])
        let spacing = try markHeadings("\n\n# Title\n\ntext\n", document: &document)
        XCTAssertEqual(try restoreHeadings("\(spacing[0].start)Title\(spacing[0].end)\ntext", spacing: spacing), "\n\nTitle\n\ntext")
        XCTAssertThrowsError(try restoreHeadings("Title", spacing: spacing))
        XCTAssertThrowsError(try markHeadings("Title\n=====\n", document: &document))
    }

    func testFrozenWrappingOracle() throws {
        struct Case: Decodable { let text: String; let columns: Int; let expected: [String] }
        let cases = try JSONDecoder().decode([Case].self,
            from: Data(contentsOf: fixtures.appendingPathComponent("wrapping.json")))
        XCTAssertEqual(cases.count, 1565)
        for item in cases {
            XCTAssertEqual(try wrapLine(item.text, columns: item.columns), item.expected,
                "columns=\(item.columns), text=\(String(reflecting: item.text))")
        }
    }
}
