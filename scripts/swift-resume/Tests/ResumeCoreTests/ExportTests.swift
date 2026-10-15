import Foundation
import XCTest
@testable import ResumeCore

// Expected outputs were produced by the retired Python generator and frozen as fixtures.
let fixtures = URL(fileURLWithPath: #filePath).deletingLastPathComponent().appendingPathComponent("Fixtures")

private let goldenNames = [
    "lf", "crlf", "outside-digest", "unicode", "unicode-renderer",
    "pagination", "empty-printable-lines", "nested-heading",
]

private let template = Data(
    "Preamble\twith tab\n<!-- resume:body:start -->\nold body\n<!-- resume:body:end -->\nSuffix without final newline".utf8)

final class ExportTests: XCTestCase {
    private var directory: URL!

    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("sync-resume-tests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: directory.path)
        try FileManager.default.removeItem(at: directory)
    }

    private func file(_ name: String) -> URL { directory.appendingPathComponent(name) }

    private func outputs() throws -> [Data] {
        try ["RESUME.txt", "RESUME.pdf"].map { try Data(contentsOf: file($0)) }
    }

    private func assertNoScratch(file: StaticString = #filePath, line: UInt = #line) throws {
        let names = try FileManager.default.contentsOfDirectory(atPath: directory.path)
        XCTAssertFalse(names.contains { $0 == "RESUME.pdf.tmp" || $0.hasPrefix(".sync-resume-work-") },
            "temporary files remain: \(names)", file: file, line: line)
    }

    private func prepare(readme: Data, resume: Data = template) throws {
        try readme.write(to: file("README.md"))
        try resume.write(to: file("RESUME.txt"))
        try Data("existing-pdf".utf8).write(to: file("RESUME.pdf"))
    }

    /// Runs a failing export and checks that it reported an error without changing outputs.
    private func assertSafeFailure(_ name: String, font: String? = nil,
                                   file: StaticString = #filePath, line: UInt = #line) throws {
        let before = try outputs()
        XCTAssertThrowsError(try synchronize(root: directory, fontPath: font ?? defaultFont),
            name, file: file, line: line)
        XCTAssertEqual(try outputs(), before, "\(name): outputs changed", file: file, line: line)
        try assertNoScratch(file: file, line: line)
    }

    private let defaultFont = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

    func testGoldenExportsMatchFrozenPythonOutput() throws {
        for name in goldenNames {
            let source = fixtures.appendingPathComponent(name)
            for item in try FileManager.default.contentsOfDirectory(atPath: directory.path) {
                try FileManager.default.removeItem(at: file(item))
            }
            try FileManager.default.copyItem(at: source.appendingPathComponent("README.md"), to: file("README.md"))
            try FileManager.default.copyItem(at: source.appendingPathComponent("input.txt"), to: file("RESUME.txt"))
            let layoutURL = file("layout.json")
            try synchronize(root: directory, layoutDestination: layoutURL)

            XCTAssertEqual(try Data(contentsOf: file("RESUME.txt")),
                try Data(contentsOf: source.appendingPathComponent("expected.txt")), "\(name): text bytes differ")
            let expected = try JSONDecoder().decode(Layout.self,
                from: Data(contentsOf: source.appendingPathComponent("layout.json")))
            let actual = try JSONDecoder().decode(Layout.self, from: Data(contentsOf: layoutURL))
            XCTAssertEqual(actual.columns, expected.columns, "\(name): columns differ")
            XCTAssertEqual(actual.characterWidth, expected.characterWidth, accuracy: 1e-10, "\(name): metrics differ")
            XCTAssertEqual(actual.lines, expected.lines, "\(name): wrapped lines or placement differ")

            let pdf = try Data(contentsOf: file("RESUME.pdf"))
            XCTAssertTrue(pdf.starts(with: Data("%PDF-".utf8)), "\(name): not a PDF")
            let first = try outputs()
            try synchronize(root: directory)
            XCTAssertEqual(try outputs(), first, "\(name): regeneration is not deterministic")
            try assertNoScratch()
        }
    }

    func testInvalidSourcesFailWithoutPublishing() throws {
        let marked = try String(contentsOf: fixtures.appendingPathComponent("lf/README.md"), encoding: .utf8)
        let invalid: [(String, Data)] = [
            ("missing-marker", Data("# no markers\n".utf8)),
            ("duplicate-marker", Data(("<!-- resume:start -->\n" + marked).utf8)),
            ("reversed-marker", Data("<!-- resume:end -->\n<!-- resume:start -->\n".utf8)),
            ("empty-source", Data("<!-- resume:start -->\n \n<!-- resume:end -->\n".utf8)),
            ("invalid-utf8", Data("<!-- resume:start -->\n".utf8) + Data([0xff]) + Data("\n<!-- resume:end -->\n".utf8)),
            ("setext-heading", Data("<!-- resume:start -->\nHeading\n=======\n<!-- resume:end -->\n".utf8)),
            ("missing-glyph", Data("<!-- resume:start -->\n# Test\n\n\u{1F680}\n<!-- resume:end -->\n".utf8)),
            ("empty-conversion", Data("<!-- resume:start -->\n<!-- hidden -->\n<!-- resume:end -->\n".utf8)),
        ]
        for (name, readme) in invalid {
            try prepare(readme: readme)
            try assertSafeFailure(name)
        }
        let templateText = String(decoding: template, as: UTF8.self)
        let invalidTemplates: [(String, Data)] = [
            ("missing-body-marker", Data("no markers\n".utf8)),
            ("duplicate-body-marker", Data("<!-- resume:body:start -->\n".utf8) + template),
            ("reversed-body-marker", Data("<!-- resume:body:end -->\n<!-- resume:body:start -->\n".utf8)),
            ("body-marker-no-lf", Data(templateText.replacingOccurrences(
                of: "<!-- resume:body:start -->\n", with: "<!-- resume:body:start -->\r").utf8)),
            ("invalid-printable-utf8", Data([0xff]) + template.dropFirst("Preamble".utf8.count)),
        ]
        for (name, resume) in invalidTemplates {
            try prepare(readme: Data(marked.utf8), resume: resume)
            try assertSafeFailure(name)
        }
        try prepare(readme: Data(marked.utf8))
        try assertSafeFailure("missing-font", font: file("missing.ttf").path)
    }

    func testPandocFailuresLeaveOutputsUnchanged() throws {
        let marked = try Data(contentsOf: fixtures.appendingPathComponent("lf/README.md"))
        let tools = directory.appendingPathComponent("tools", isDirectory: true)
        try FileManager.default.createDirectory(at: tools, withIntermediateDirectories: false)
        let originalPath = ProcessInfo.processInfo.environment["PATH"] ?? "/usr/bin:/bin"
        defer { setenv("PATH", originalPath, 1) }

        try prepare(readme: marked)
        setenv("PATH", tools.path, 1)
        try assertSafeFailure("missing-pandoc")

        for (name, script) in [
            ("pandoc-nonzero", "#!/bin/sh\nprintf 'deliberate pandoc failure\\n' >&2\nexit 23\n"),
            ("pandoc-large-stderr", "#!/bin/sh\nhead -c 200000 /dev/zero >&2\nexit 24\n"),
            ("pandoc-invalid-json", "#!/bin/sh\nprintf 'not json'\n"),
        ] {
            let tool = tools.appendingPathComponent("pandoc")
            try? FileManager.default.removeItem(at: tool)
            try Data(script.utf8).write(to: tool)
            try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: tool.path)
            setenv("PATH", "\(tools.path):/usr/bin:/bin", 1)
            try assertSafeFailure(name)
        }
    }

    func testStagingAndReplacementFailures() throws {
        try XCTSkipIf(geteuid() == 0, "Permission checks are not meaningful as root")
        let marked = try Data(contentsOf: fixtures.appendingPathComponent("lf/README.md"))
        let staging = file("RESUME.pdf.tmp")

        try prepare(readme: marked)
        try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: false)
        XCTAssertThrowsError(try synchronize(root: directory))
        XCTAssertEqual(try Data(contentsOf: file("RESUME.txt")), template)
        try FileManager.default.removeItem(at: staging)

        try FileManager.default.createSymbolicLink(at: staging, withDestinationURL: file("missing-target.pdf"))
        XCTAssertThrowsError(try synchronize(root: directory))
        XCTAssertFalse(FileManager.default.fileExists(atPath: file("missing-target.pdf").path))
        try FileManager.default.removeItem(at: staging)

        try FileManager.default.setAttributes([.posixPermissions: 0o444], ofItemAtPath: file("RESUME.txt").path)
        XCTAssertThrowsError(try synchronize(root: directory))
        XCTAssertEqual(try Data(contentsOf: file("RESUME.txt")), template)
        try assertNoScratch()
        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: file("RESUME.txt").path)

        // The text export is written before the PDF is renamed into place.
        try FileManager.default.removeItem(at: file("RESUME.pdf"))
        try FileManager.default.createDirectory(at: file("RESUME.pdf"), withIntermediateDirectories: false)
        XCTAssertThrowsError(try synchronize(root: directory))
        XCTAssertNotEqual(try Data(contentsOf: file("RESUME.txt")), template)
        try assertNoScratch()
    }
}
