import Foundation
import CCairo
import CFreeType

nonisolated(unsafe) private let fontKey: UnsafeMutablePointer<cairo_user_data_key_t> = {
    let key = UnsafeMutablePointer<cairo_user_data_key_t>.allocate(capacity: 1)
    key.initialize(to: cairo_user_data_key_t())
    return key
}()

private final class FontOwner {
    let library: FT_Library
    let face: FT_Face

    init(path: String) throws {
        var library: FT_Library?
        guard FT_Init_FreeType(&library) == 0, let library else { throw ResumeError("FreeType initialization failed") }
        var face: FT_Face?
        let status = FT_New_Face(library, path, 0, &face)
        guard status == 0, let face else {
            FT_Done_FreeType(library)
            throw ResumeError("Cannot load font \(path) (FreeType \(status))")
        }
        self.library = library
        self.face = face
    }

    deinit { FT_Done_Face(face); FT_Done_FreeType(library) }
}

private func check(_ status: cairo_status_t, _ operation: String) throws {
    guard status == CAIRO_STATUS_SUCCESS else {
        throw ResumeError("\(operation): \(String(cString: cairo_status_to_string(status)))")
    }
}

public struct LayoutLine: Codable, Equatable {
    public let text: String
    public let page: Int
    public let x: Double
    public let y: Double
}

public struct Layout: Codable {
    public let columns: Int
    public let characterWidth: Double
    public let lines: [LayoutLine]
}

public func renderPDF(_ text: String, destination: URL, sourceDigest: String,
                      fontPath: String = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf") throws -> Layout {
    let owner = try FontOwner(path: fontPath)
    let face = owner.face
    guard FT_Load_Char(face, 77, FT_Int32(FT_LOAD_NO_SCALE)) == 0, face.pointee.units_per_EM > 0 else {
        throw ResumeError("Cannot measure font M advance")
    }
    let advance = Double(face.pointee.glyph.pointee.metrics.horiAdvance) / Double(face.pointee.units_per_EM) * 9
    guard advance.isFinite, advance > 0 else { throw ResumeError("Invalid font advance") }
    let columns = Int(528 / advance)
    var layout: [LayoutLine] = []
    var page = 1
    var y = 750.0
    for source in lines(text) {
        for part in try wrapLine(source, columns: columns) {
            for scalar in part.unicodeScalars {
                guard scalar.value != 0, FT_Get_Char_Index(face, FT_ULong(scalar.value)) != 0 else {
                    throw ResumeError(String(format: "Font has no glyph for U+%04X", scalar.value))
                }
            }
            if y < 42 { page += 1; y = 750 }
            layout.append(LayoutLine(text: part, page: page, x: 42, y: y))
            y -= 12
        }
    }
    guard let font = cairo_ft_font_face_create_for_ft_face(face, Int32(FT_LOAD_NO_HINTING)) else {
        throw ResumeError("Cannot create Cairo font face")
    }
    defer { cairo_font_face_destroy(font) }
    try check(cairo_font_face_status(font), "Create font face")
    let retained = Unmanaged.passRetained(owner)
    let status = cairo_font_face_set_user_data(font, fontKey, retained.toOpaque(), {
        if let pointer = $0 { Unmanaged<FontOwner>.fromOpaque(pointer).release() }
    })
    if status != CAIRO_STATUS_SUCCESS { retained.release(); try check(status, "Attach font lifetime") }

    guard let surface = cairo_pdf_surface_create(destination.path, 612, 792) else {
        throw ResumeError("Cannot create PDF surface")
    }
    defer { cairo_surface_destroy(surface) }
    try check(cairo_surface_status(surface), "Create PDF surface")
    cairo_pdf_surface_set_metadata(surface, CAIRO_PDF_METADATA_TITLE, "Resume")
    cairo_pdf_surface_set_metadata(surface, CAIRO_PDF_METADATA_SUBJECT, "README SHA-256: \(sourceDigest)")
    cairo_pdf_surface_set_metadata(surface, CAIRO_PDF_METADATA_CREATE_DATE, "2000-01-01T00:00:00Z")
    cairo_pdf_surface_set_metadata(surface, CAIRO_PDF_METADATA_MOD_DATE, "2000-01-01T00:00:00Z")
    guard let context = cairo_create(surface) else {
        throw ResumeError("Cannot create Cairo drawing context")
    }
    defer { cairo_destroy(context) }
    try check(cairo_status(context), "Create drawing context")
    guard let options = cairo_font_options_create() else {
        throw ResumeError("Cannot create Cairo font options")
    }
    defer { cairo_font_options_destroy(options) }
    cairo_font_options_set_hint_style(options, CAIRO_HINT_STYLE_NONE)
    cairo_font_options_set_hint_metrics(options, CAIRO_HINT_METRICS_OFF)
    try check(cairo_font_options_status(options), "Configure font options")
    cairo_set_font_options(context, options)
    cairo_set_font_face(context, font)
    cairo_set_font_size(context, 9)
    cairo_set_source_rgb(context, 0, 0, 0)
    let scaled = cairo_get_scaled_font(context)
    try check(cairo_scaled_font_status(scaled), "Configure scaled font")
    var currentPage = 1
    for line in layout {
        if line.page != currentPage { cairo_show_page(context); currentPage = line.page }
        if !line.text.isEmpty {
            var glyphs: UnsafeMutablePointer<cairo_glyph_t>?
            var glyphCount: Int32 = 0
            var clusters: UnsafeMutablePointer<cairo_text_cluster_t>?
            var clusterCount: Int32 = 0
            var flags = cairo_text_cluster_flags_t(rawValue: 0)
            defer {
                if let glyphs { cairo_glyph_free(glyphs) }
                if let clusters { cairo_text_cluster_free(clusters) }
            }
            let bytes = line.text.utf8.count
            guard bytes <= Int(Int32.max) else { throw ResumeError("Text line is too large") }
            try check(cairo_scaled_font_text_to_glyphs(scaled, line.x, 792 - line.y, line.text, Int32(bytes),
                &glyphs, &glyphCount, &clusters, &clusterCount, &flags), "Convert text to glyphs")
            cairo_show_text_glyphs(context, line.text, Int32(bytes), glyphs, glyphCount, clusters, clusterCount, flags)
            try check(cairo_status(context), "Draw text")
        }
    }
    cairo_show_page(context)
    try check(cairo_status(context), "Finish page")
    cairo_surface_finish(surface)
    try check(cairo_surface_status(surface), "Finish PDF")
    return Layout(columns: columns, characterWidth: advance, lines: layout)
}
