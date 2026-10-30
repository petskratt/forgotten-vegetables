import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_commonmark_renders_tables_and_does_not_leak_emphasis():
    script = r"""
const cm = require("./viewer/vendor/commonmark.js");
const md = require("./viewer/markdown.js");
const safe = (url) => (/^https?:\/\//i.test(String(url || "").trim()) ? String(url).trim() : "");

const table = md.render(cm, "| A | B |\n| --- | --- |\n| 1 | **two** |\n", safe);
if (!table.includes("<table>") || !table.includes("<td>1</td>") || !table.includes("<strong>two</strong>")) {
  console.error(table);
  process.exit(1);
}

const emph = md.render(cm, "hello *no close\n\nstill plain **also open", safe);
if (emph.includes("<em>") || emph.includes("<strong>")) {
  console.error(emph);
  process.exit(2);
}
if (!emph.includes("still plain")) process.exit(3);

const nasty = md.render(cm, "<script>alert(1)</script>\n\n**ok**", safe);
if (nasty.includes("<script>") || !nasty.includes("<strong>ok</strong>")) {
  console.error(nasty);
  process.exit(4);
}

const js = md.render(cm, "[x](javascript:alert(1))", safe);
if (js.includes("javascript:") || js.includes("<a")) {
  console.error(js);
  process.exit(5);
}

const mention = md.render(cm, "hi @alice and :smile:", safe);
if (!mention.includes("@alice") || !mention.includes(":smile:") || mention.includes("data-mention")) {
  console.error(mention);
  process.exit(6);
}

const lines = md.render(cm, "one\ntwo", safe);
if (!lines.includes("<br")) {
  console.error(lines);
  process.exit(7);
}
"""
    result = subprocess.run(
        ["node", "--input-type=commonjs", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
