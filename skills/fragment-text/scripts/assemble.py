#!/usr/bin/env python3
"""Assemble model-authored fragments. This is NOT a watermark detector."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

FORMAT = "fragment-text/v1"
MAX_BYTES = 2_000_000
MAX_PARTS = 40_000
MAX_FRAGMENT = 8


class InvalidTransport(ValueError):
    pass


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise InvalidTransport(f"Duplicate key: {key}")
        obj[key] = value
    return obj


def decode(raw):
    if len(raw) > MAX_BYTES:
        raise InvalidTransport("Input exceeds 2 MB")
    try:
        obj = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_object)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise InvalidTransport("Expected a complete UTF-8 JSON document") from exc
    if not isinstance(obj, dict) or set(obj) != {"format", "blocks", "complete"}:
        raise InvalidTransport("Expected format, blocks, complete; no extra fields")
    if obj["format"] != FORMAT or obj["complete"] is not True:
        raise InvalidTransport("Unsupported format or missing complete:true")
    blocks = obj["blocks"]
    if not isinstance(blocks, list) or not 1 <= len(blocks) <= 2000:
        raise InvalidTransport("Expected 1..2000 numbered blocks")
    parts = []
    for index, block in enumerate(blocks):
        if not isinstance(block, dict) or set(block) != {"n", "parts"}:
            raise InvalidTransport(f"Block {index}: expected n and parts")
        if type(block["n"]) is not int or block["n"] != index:
            raise InvalidTransport(f"Block {index}: missing, reordered or repeated block")
        fragments = block["parts"]
        if not isinstance(fragments, list) or not 1 <= len(fragments) <= 256:
            raise InvalidTransport(f"Block {index}: expected 1..256 fragments")
        for part in fragments:
            if not isinstance(part, str) or not 1 <= len(part) <= MAX_FRAGMENT:
                raise InvalidTransport(f"Block {index}: fragments must contain 1..8 Unicode code points")
            try:
                part.encode("utf-8", errors="strict")
            except UnicodeError as exc:
                raise InvalidTransport(f"Block {index}: unpaired Unicode surrogate") from exc
            if any(ord(c) < 32 and c not in "\r\n\t" for c in part):
                raise InvalidTransport(f"Block {index}: unsupported control character")
        parts.extend(fragments)
        if len(parts) > MAX_PARTS:
            raise InvalidTransport("Too many fragments")
    return "".join(parts), len(parts), len(blocks)


def viewer(text):
    # Text never enters HTML or JavaScript syntax. Escape '<' to protect script boundaries.
    data = json.dumps(text, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return '''<!doctype html>
<html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; base-uri 'none'; form-action 'none'">
<title>Fragment Text — ответ</title>
<style>
:root{color-scheme:light dark;font-family:system-ui,sans-serif;background:#13171c;color:#e9edf2}
body{max-width:880px;margin:48px auto;padding:0 24px}header{display:flex;gap:16px;align-items:center;flex-wrap:wrap}
h1{font-size:22px;margin-right:auto}button{font:inherit;background:#b7f0c8;color:#13221a;border:0;border-radius:9px;padding:10px 16px;cursor:pointer}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:17px/1.7 system-ui,sans-serif;padding:28px;background:#1c222a;border-radius:14px}
.note{color:#a8b4c2;font-size:14px}#status{min-height:24px}
</style>
<header><h1>Fragment Text</h1><button id="copy">Копировать</button><button id="save">Скачать .txt</button></header>
<p class="note">Ответ собран локально. Наличие водяного знака не проверялось.</p>
<pre id="answer" tabindex="0"></pre><p id="status" role="status" aria-live="polite"></p>
<script type="application/json" id="payload">''' + data + '''</script>
<script>
const text=JSON.parse(document.getElementById('payload').textContent);
const answer=document.getElementById('answer');answer.textContent=text;
const status=document.getElementById('status');
document.getElementById('copy').addEventListener('click',async()=>{
  try{await navigator.clipboard.writeText(text);status.textContent='Скопировано';}
  catch{const selection=window.getSelection();const range=document.createRange();range.selectNodeContents(answer);selection.removeAllRanges();selection.addRange(range);status.textContent='Нажмите Ctrl+C или ⌘C, чтобы скопировать выделенный текст.';}
});
document.getElementById('save').addEventListener('click',()=>{
  const url=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download='answer.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
</script></html>
'''


def assemble(source, output):
    with source.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    text, count, blocks = decode(raw)
    content = text.encode("utf-8")
    report = {
        "format": FORMAT,
        "watermark_status": "not_tested",
        "generation_origin": "not_verified",
        "parts": count,
        "blocks": blocks,
        "characters": len(text),
        "transport_sha256": hashlib.sha256(raw).hexdigest(),
        "text_sha256": hashlib.sha256(content).hexdigest(),
    }
    # Exclusive directory creation avoids silently overwriting earlier answers.
    output.mkdir(parents=True, exist_ok=False)
    (output / "answer.txt").write_bytes(content)
    (output / "answer.html").write_text(viewer(text), encoding="utf-8", newline="")
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return {"answer": str((output / "answer.txt").resolve()),
            "preview": str((output / "answer.html").resolve()),
            "report": str((output / "report.json").resolve()),
            "watermark_status": "not_tested"}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True, help="A NEW directory for this answer")
    args = parser.parse_args()
    try:
        print(json.dumps(assemble(args.input, args.output_dir), ensure_ascii=True))
    except (OSError, InvalidTransport) as exc:
        print(f"Assembly failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
