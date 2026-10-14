"""Exercise the workflows' artifact handoff without touching production exports."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


def workflow_script(filename: str, step: str) -> str:
    source = (ROOT / ".github/workflows" / filename).read_text()
    block = source.split(f"      - name: {step}\n", 1)[1]
    block = block.split("\n      - name:", 1)[0]
    return textwrap.dedent(block.split("        run: |\n", 1)[1]).strip()


class ResumeWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        work = ROOT / ".qualification"
        work.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=work, prefix="workflow-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "README.md").write_bytes(b"source for artifact test\n")
        output = self.root / ".qualification/outputs/actual/swift"
        output.mkdir(parents=True)
        (output / "RESUME.txt").write_bytes(b"qualified text\n")
        (output / "RESUME.pdf").write_bytes(b"qualified PDF bytes\n")
        self.prepare = workflow_script(
            "qualify-swift-resume.yml", "Prepare qualified exports for this commit"
        )
        self.publish = workflow_script(
            "sync-resume.yml", "Verify and publish qualified exports"
        )
        subprocess.run(
            ["bash", "--noprofile", "--norc", "-euo", "pipefail", "-c", self.prepare],
            cwd=self.root, capture_output=True, check=True,
        )

    def run_publication(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", "--noprofile", "--norc", "-euo", "pipefail", "-c", self.publish],
            cwd=self.root, capture_output=True,
        )

    def exports(self) -> list[bytes]:
        return [(self.root / name).read_bytes() for name in ("RESUME.txt", "RESUME.pdf")]

    def test_qualified_publication_is_repeatable(self) -> None:
        result = self.run_publication()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.exports(), [b"qualified text\n", b"qualified PDF bytes\n"])
        result = self.run_publication()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.exports(), [b"qualified text\n", b"qualified PDF bytes\n"])

    def test_invalid_handoff_fails_before_publication(self) -> None:
        artifact = self.root / ".qualification/qualified-export"
        for path, corrupt in (
            (artifact / "commit.txt", b"wrong commit\n"),
            (self.root / "README.md", b"wrong source\n"),
            (artifact / "RESUME.txt", b"wrong text\n"),
            (artifact / "RESUME.pdf", b"wrong PDF\n"),
        ):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(corrupt)
                try:
                    result = self.run_publication()
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse((self.root / "RESUME.txt").exists())
                    self.assertFalse((self.root / "RESUME.pdf").exists())
                finally:
                    path.write_bytes(original)
        shutil.rmtree(artifact)
        self.assertNotEqual(self.run_publication().returncode, 0)
        self.assertFalse((self.root / "RESUME.txt").exists())
        self.assertFalse((self.root / "RESUME.pdf").exists())


if __name__ == "__main__":
    unittest.main()
