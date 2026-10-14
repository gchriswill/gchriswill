import Foundation

public func synchronize(root: URL, fontPath: String = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
                        layoutDestination: URL? = nil) throws {
    let readme = try Data(contentsOf: root.appendingPathComponent("README.md"))
    let sourceDigest = digest(readme)
    let readmeLines = byteLines(readme)
    let (first, last) = try markedSection(readmeLines, start: "<!-- resume:start -->", end: "<!-- resume:end -->")
    let markdown = try utf8(readmeLines[(first + 1)..<last].reduce(Data(), +))
    guard !stripped(markdown).isEmpty else { throw ResumeError("The README resume section is empty.") }
    let pandoc = try Pandoc(root: root)
    do {
        let parsed = try pandoc.run(["--from=gfm", "--to=json"], input: Data(markdown.utf8))
        var document = try preserveLinks(JSONDecoder().decode(JSONValue.self, from: parsed))
        let spacing = try markHeadings(markdown, document: &document)
        let converted = try pandoc.run(["--from=json", "--to=plain", "--wrap=none"], input: JSONEncoder().encode(document))
        var body = stripped(try utf8(converted))
        guard !body.isEmpty else { throw ResumeError("The converted resume body is empty.") }
        body = try restoreHeadings(body, spacing: spacing)
        body = try normalizeBullets(body)
        let resumeURL = root.appendingPathComponent("RESUME.txt")
        let resumeLines = byteLines(try Data(contentsOf: resumeURL))
        let (bodyStart, bodyEnd) = try markedSection(resumeLines,
            start: "<!-- resume:body:start -->", end: "<!-- resume:body:end -->")
        guard resumeLines[bodyStart].last == 10 else { throw ResumeError("The body start marker must end with a newline.") }
        let newline = resumeLines[bodyStart].suffix(2) == Data([13, 10]) ? "\r\n" : "\n"
        let bodyData = Data((body.replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\n", with: newline) + newline).utf8)
        let prefix = resumeLines[...bodyStart].reduce(Data(), +)
        let suffix = resumeLines[bodyEnd...].reduce(Data(), +)
        let marker = Data(("<!-- resume:source:sha256 \(sourceDigest) -->" + newline).utf8)
        let printable = resumeLines[..<bodyStart].reduce(Data(), +) + bodyData
            + resumeLines[(bodyEnd + 1)...].reduce(Data(), +)
        let temporary = root.appendingPathComponent("RESUME.pdf.tmp")
        var stagingInfo = stat()
        if lstat(temporary.path, &stagingInfo) == 0 {
            guard stagingInfo.st_mode & mode_t(S_IFMT) == mode_t(S_IFREG) else {
                throw ResumeError("PDF staging path must be a regular file: \(temporary.path)")
            }
        } else if errno != ENOENT {
            throw ResumeError("Cannot inspect PDF staging path: \(String(cString: strerror(errno)))")
        }
        do {
            let layout = try renderPDF(utf8(printable), destination: temporary, sourceDigest: sourceDigest, fontPath: fontPath)
            if let layoutDestination { try JSONEncoder().encode(layout).write(to: layoutDestination) }
            try (prefix + marker + bodyData + suffix).write(to: resumeURL)
            // POSIX rename replaces an existing PDF without an intervening delete.
            if rename(temporary.path, root.appendingPathComponent("RESUME.pdf").path) != 0 {
                throw ResumeError("Cannot replace RESUME.pdf: \(String(cString: strerror(errno)))")
            }
        } catch {
            if FileManager.default.fileExists(atPath: temporary.path) {
                do { try FileManager.default.removeItem(at: temporary) }
                catch let cleanup { throw ResumeError("\(error); PDF cleanup failed: \(cleanup)") }
            }
            throw error
        }
        try pandoc.removeScratch()
    } catch {
        if FileManager.default.fileExists(atPath: pandoc.scratch.path) {
            do { try pandoc.removeScratch() }
            catch let cleanup { throw ResumeError("\(error); scratch cleanup failed: \(cleanup)") }
        }
        throw error
    }
}
