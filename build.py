"""Build the JVDA NVDA add-on package."""

from pathlib import Path
import re
import subprocess
import sys
import zipfile


ROOT = Path(__file__).parent
INCLUDED = (
	"manifest.ini", "README.md", "CHANGELOG.md", "LICENSE",
	"command-compatibility.json", "commands.md", "user-guide.md", "doc",
	"appModules", "globalPlugins",
)
_ZIP_TIMESTAMP = (2020, 1, 1, 0, 0, 0)
VERSION_TEMPLATES = (
	("CHANGELOG.md.in", "CHANGELOG.md"),
	("doc/en/changes.html.in", "doc/en/changes.html"),
	("doc/en/readme.html.in", "doc/en/readme.html"),
)


def addonVersion() -> str:
	manifest = (ROOT / "manifest.ini").read_text(encoding="utf-8")
	match = re.search(r'^version\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"\s*$', manifest, re.M)
	if not match:
		raise SystemExit("manifest.ini must contain an x.y.z version")
	return match.group(1)


def renderVersionTemplates(version: str | None = None) -> list[Path]:
	version = version or addonVersion()
	outputs = []
	for templateName, outputName in VERSION_TEMPLATES:
		template = ROOT / templateName
		text = template.read_text(encoding="utf-8")
		if "$version" not in text:
			raise SystemExit(f"Version template has no $version marker: {template}")
		output = ROOT / outputName
		output.write_text(text.replace("$version", version), encoding="utf-8")
		outputs.append(output)
	return outputs


def runTests() -> None:
	projectRoot = ROOT.parent
	testsRoot = projectRoot / "tests"
	if not testsRoot.is_dir():
		# Public source snapshots intentionally omit the private development
		# test corpus. The release publisher tests before exporting a snapshot.
		return
	result = subprocess.run(
		[
			sys.executable,
			"-m",
			"unittest",
			"-q",
			"tests/test_jaws_keymap.py",
			"tests/test_space_layer.py",
			"tests/test_jvda_behavior.py",
			"tests/test_jaws_keymap_parser.py",
			"tests/test_jvda_coverage.py",
			"tests/test_jvda_text_utils.py",
			"tests/test_winamp.py",
			"tests/test_publish_github.py",
		],
		cwd=projectRoot,
		check=False,
	)
	if result.returncode:
		raise SystemExit("JVDA regression tests failed")


def _sources():
	for item in INCLUDED:
		path = ROOT / item
		if path.is_file():
			yield path
		elif path.is_dir():
			yield from sorted(
				(source for source in path.rglob("*")
				 if source.is_file()
				 and "__pycache__" not in source.parts
				 and source.suffix != ".in"),
				key=lambda source: source.as_posix(),
			)


def _writeFile(archive: zipfile.ZipFile, source: Path) -> None:
	info = zipfile.ZipInfo(source.relative_to(ROOT).as_posix(), _ZIP_TIMESTAMP)
	info.compress_type = zipfile.ZIP_DEFLATED
	info.external_attr = 0o100644 << 16
	archive.writestr(info, source.read_bytes())


def main() -> None:
	renderVersionTemplates()
	runTests()
	output = ROOT / "dist" / f"jvda-{addonVersion()}.nvda-addon"
	output.parent.mkdir(exist_ok=True)
	with zipfile.ZipFile(output, "w") as archive:
		for source in _sources():
			_writeFile(archive, source)
	print(output)


if __name__ == "__main__":
	main()
