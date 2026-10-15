// swift-tools-version: 6.3
import PackageDescription

let package = Package(
    name: "SwiftResume",
    products: [.executable(name: "sync-resume", targets: ["SyncResume"])],
    dependencies: [
        .package(url: "https://github.com/apple/swift-crypto.git", exact: "5.0.1")
    ],
    targets: [
        .systemLibrary(name: "CCairo", pkgConfig: "cairo", providers: [.apt(["libcairo2-dev"])]),
        .systemLibrary(name: "CFreeType", pkgConfig: "freetype2", providers: [.apt(["libfreetype-dev"])]),
        .target(name: "ResumeCore", dependencies: ["CCairo", "CFreeType", .product(name: "Crypto", package: "swift-crypto")]),
        .executableTarget(name: "SyncResume", dependencies: ["ResumeCore"]),
        .testTarget(name: "ResumeCoreTests", dependencies: ["ResumeCore"], exclude: ["Fixtures"])
    ]
)
