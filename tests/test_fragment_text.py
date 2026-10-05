import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "fragment-text" / "scripts" / "assemble.py"


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


codec = module("assemble", SCRIPT)
setup = module("setup_fragment_text", ROOT / "setup.py")


def wire(text):
    """Test-only encoder. Encoding already-written text is a NEGATIVE control."""
    parts = [text[i:i + 4] for i in range(0, len(text), 4)]
    blocks = [{"n": i // 256, "parts": parts[i:i + 256]} for i in range(0, len(parts), 256)]
    return json.dumps({"format": codec.FORMAT, "blocks": blocks, "complete": True}, ensure_ascii=True).encode()


class TransportTests(unittest.TestCase):
    def test_unicode_whitespace_code_and_citations_survive_exactly(self):
        text = '  Русский e\u0301 👩🏽\u200d💻 中文\u00a0\u200b\n\r\n\t`x = "</script>"`\n[Источник](https://example.org/a?q=1&n=2)  '
        self.assertEqual(codec.decode(wire(text))[0].encode(), text.encode())

    def test_negative_control_is_identity_not_watermark_removal(self):
        text = "An already generated text retains exactly its original words and characters."
        self.assertEqual(codec.decode(wire(text))[0], text)

    def test_multiblock_and_bom(self):
        text = "аб👩\n" * 400
        self.assertEqual(codec.decode(b"\xef\xbb\xbf" + wire(text))[0], text)

    def test_incomplete_and_invalid_documents_rejected(self):
        raw = wire("example")
        cases = [raw[:-1], b"not json", b"\xff", raw + b" trailing", b"[]",
                 raw.replace(b'"complete": true', b'"complete": false'),
                 raw.replace(b'"complete": true', b'"complete": 1'),
                 raw.replace(b'"complete": true', b'"complete": true, "complete": true'),
                 raw.replace(b'"n": 0', b'"n": true'),
                 raw.replace(b'"n": 0', b'"n": 1'),
                 raw.replace(b'"n": 0', b'"n": 0, "extra": 1'),
                 raw.replace(b'fragment-text/v1', b'fragment-text/v2')]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(codec.InvalidTransport):
                codec.decode(case)

    def test_fragment_types_sizes_and_surrogates(self):
        for part in ["", "123456789", 1, None, [], "\ud800", "a\x00", "a\x1b"]:
            obj = {"format": codec.FORMAT, "blocks": [{"n": 0, "parts": [part]}], "complete": True}
            with self.subTest(part=repr(part)), self.assertRaises(codec.InvalidTransport):
                codec.decode(json.dumps(obj).encode())

    def test_lost_and_reordered_blocks(self):
        obj = json.loads(wire("abcd" * 1000))
        for blocks in [obj["blocks"][1:], list(reversed(obj["blocks"])), obj["blocks"] * 2]:
            obj2 = dict(obj, blocks=blocks)
            with self.assertRaises(codec.InvalidTransport):
                codec.decode(json.dumps(obj2).encode())

    def test_resource_limits(self):
        with self.assertRaises(codec.InvalidTransport):
            codec.decode(b" " * (codec.MAX_BYTES + 1))
        obj = {"format": codec.FORMAT, "blocks": [{"n": 0, "parts": ["a"] * 257}], "complete": True}
        with self.assertRaises(codec.InvalidTransport):
            codec.decode(json.dumps(obj).encode())

    def test_cli_artifacts_hash_and_no_overwrite(self):
        import hashlib
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            source = folder / "input.json"
            text = "Ответ\r\n  with spaces \n"
            source.write_bytes(wire(text))
            output = folder / "answer"
            cmd = [sys.executable, str(SCRIPT), str(source), "--output-dir", str(output)]
            run = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertNotIn(text, run.stdout)
            self.assertEqual((output / "answer.txt").read_bytes(), text.encode())
            report = json.loads((output / "report.json").read_bytes())
            self.assertEqual(report["text_sha256"], hashlib.sha256(text.encode()).hexdigest())
            self.assertEqual(report["watermark_status"], "not_tested")
            run = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(run.returncode, 2)
            self.assertEqual((output / "answer.txt").read_bytes(), text.encode())

    def test_invalid_input_creates_no_answer(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "bad.json"
            source.write_bytes(b'{"format":')
            output = Path(td) / "result"
            with self.assertRaises(codec.InvalidTransport):
                codec.assemble(source, output)
            self.assertFalse(output.exists())

    def test_viewer_payload_cannot_escape_into_markup(self):
        text = '</script><script>globalThis.pwned=true</script><img src="https://evil.invalid/">\r\n & \u2028'
        html = codec.viewer(text)
        self.assertNotIn('<img', html)
        self.assertNotIn('<script>globalThis', html)
        match = re.search(r'<script type="application/json" id="payload">(.*?)</script>', html, re.S)
        self.assertEqual(json.loads(match.group(1)), text)
        self.assertIn('answer.textContent=text', html)
        self.assertIn("connect-src 'none'", html)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / "codex home"
        self.home.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_install_remove_preserves_original_and_later_user_edits(self):
        target = self.home / "AGENTS.md"
        original = "# Мои инструкции\r\nDo real work.\r\n".encode()
        target.write_bytes(original)
        result = setup.install(self.home)
        self.assertTrue(result["automatic"])
        self.assertTrue(setup.status(self.home)["startup_instruction_present"])
        later = b"\nMy newer preference.\n"
        target.write_bytes(target.read_bytes() + later)
        result = setup.remove(self.home)
        self.assertEqual(target.read_bytes(), original + later)
        self.assertTrue((Path(result["preserved_backup"]) / "skill" / "SKILL.md").exists())
        self.assertFalse(setup.status(self.home)["installed"])

    def test_existing_override_is_used_and_base_unchanged(self):
        base = self.home / "AGENTS.md"
        override = self.home / "AGENTS.override.md"
        base.write_bytes(b"Base instructions")
        override.write_bytes(b"Override instructions")
        setup.install(self.home)
        self.assertEqual(base.read_bytes(), b"Base instructions")
        self.assertIn(setup.START, override.read_bytes())
        setup.remove(self.home)
        self.assertEqual(override.read_bytes(), b"Override instructions")

    def test_new_override_reports_shadowed(self):
        setup.install(self.home)
        (self.home / "AGENTS.override.md").write_text("Other instructions")
        self.assertTrue(setup.status(self.home)["shadowed_by_override"])

    def test_manual_does_not_write_instructions(self):
        setup.install(self.home, manual=True)
        self.assertFalse((self.home / "AGENTS.md").exists())
        self.assertFalse(setup.status(self.home)["startup_instruction_present"])
        setup.remove(self.home)

    def test_no_overlay_of_existing_skill(self):
        skill = self.home / "skills" / "fragment-text"
        skill.mkdir(parents=True)
        existing = skill / "mine.txt"
        existing.write_bytes(b"My content")
        with self.assertRaises(ValueError):
            setup.install(self.home)
        self.assertEqual(existing.read_bytes(), b"My content")

    def test_duplicate_install_does_not_duplicate_instructions(self):
        setup.install(self.home)
        with self.assertRaises(ValueError):
            setup.install(self.home)
        self.assertEqual((self.home / "AGENTS.md").read_bytes().count(setup.START), 1)

    def test_edited_instruction_block_not_silently_removed(self):
        setup.install(self.home)
        target = self.home / "AGENTS.md"
        target.write_bytes(target.read_bytes().replace(b"experimental", b"modified"))
        before = target.read_bytes()
        with self.assertRaises(ValueError):
            setup.remove(self.home)
        self.assertEqual(target.read_bytes(), before)
        self.assertTrue((self.home / "skills" / "fragment-text").exists())

    def test_modified_skill_is_detected_and_preserved_on_remove(self):
        setup.install(self.home)
        path = self.home / "skills" / "fragment-text" / "SKILL.md"
        path.write_bytes(b"User modification")
        self.assertIn("SKILL.md", setup.status(self.home)["changed_files"])
        backup = Path(setup.remove(self.home)["preserved_backup"])
        self.assertEqual((backup / "skill" / "SKILL.md").read_bytes(), b"User modification")

    def test_large_or_non_utf8_guidance_not_changed(self):
        path = self.home / "AGENTS.md"
        for original in [b"a" * 24000, "Русский".encode("utf-16")]:
            path.write_bytes(original)
            with self.assertRaises(ValueError):
                setup.install(self.home)
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse((self.home / "skills").exists())

    def test_cli_status_clean_home(self):
        result = subprocess.run([sys.executable, str(ROOT / "setup.py"), "status", "--codex-home", str(self.home)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"installed": False})


if __name__ == "__main__":
    unittest.main()
