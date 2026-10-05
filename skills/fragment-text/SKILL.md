---
name: fragment-text
description: >-
  Generate final prose directly as short fragments and assemble a local readable
  file with the current model. Use when Fragment Text mode is enabled or requested
  for experimental text provenance research. Not a verified watermark remover.
---

# NoTextGrain Lab (Fragment Text protocol)

Keep the current model. No external inference, API keys, background service or
additional model is needed. This is an experimental generation format, not an
off switch for server watermarking. Never describe a result as watermark-free.

## Workflow

Complete the user's actual task and research normally. For the final prose answer:

1. **Generate directly** into a UTF-8 JSON file in the task's scratch directory.
   Author the strings yourself as the answer is produced. Do not first write the
   full answer and split, encode, paraphrase or copy it using a script: that would
   only be a reversible transport of an existing text.
2. Use exactly this format, with sequential blocks starting at zero:

   ```json
   {"format":"fragment-text/v1","blocks":[{"n":0,"parts":["При","вет",", ","мир","!\n"]}],"complete":true}
   ```

   Each string contains **1..8 Unicode code points**; prefer splitting within
   words every 2..4 characters. Each block contains 1..256 strings. Start another
   numbered block when needed. Include every space, newline and punctuation mark
   explicitly. Joining parts and blocks inserts NOTHING. Preserve facts, numbers,
   quotations, names, URLs, spelling, code and citations. Use Markdown source for
   formatting. Do not add invisible characters, confusables or random visible words.
   Add `complete:true` only after finishing the answer. Limits: 2000 blocks,
   40000 parts, 2 MB JSON. For a larger task use several separate named answers.
3. Run the bundled script using a NEW output directory for this answer:

   ```text
   python "<this-skill>/scripts/assemble.py" "<scratch>/answer.fragments.json" --output-dir "<outputs>/answer-unique"
   ```

   Use the Python interpreter recorded in the user's Fragment Text startup
   instruction when present; otherwise resolve Python 3.10+ on the host. Use file
   tools or correctly quoted shell arguments; never interpolate text fragments
   into executable shell syntax. `<outputs>` follows the host's deliverable rules.
4. Check the command succeeded. On invalid fragments, fix the input and retry at
   most twice. Never report success after a failed command. Truncation or lost
   text requires regenerating the affected answer, not inventing missing content.
5. Show the returned **answer file** using the host's file-preview tool (in Codex,
   `open_in_codex` with `target.type=file` and the absolute `answer.txt` path).
   Include a clickable absolute file link in the final message. The companion HTML
   file offers copy/save buttons in a browser. If preview isn't available, the
   file link is sufficient. Do not regenerate the assembled answer in the chat.

The link/status message and progress updates are ordinary model-generated text
and are outside this experiment. If a higher-priority instruction requires an
inline response, obey it and state that this response didn't use the transport.
If execution is unavailable, explain that limitation instead of simulating assembly.
An explicit user request to disable this mode or answer inline takes precedence.

This workflow applies to final conversational prose, not to project source files,
tool arguments unrelated to this transport, binary artifacts, or hidden reasoning.
The helper validates structure only: it cannot prove that fragments were authored
directly, detect missing words inside a valid block, or assess any watermark.
