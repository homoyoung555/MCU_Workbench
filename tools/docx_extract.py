# docx 文本提取（无 pandoc 环境）：段落 + 表格转 markdown。
import io
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def cell_text(tc):
    parts = []
    for p in tc.iter("{%s}p" % NS["w"]):
        t = "".join(n.text or "" for n in p.iter("{%s}t" % NS["w"]))
        if t.strip():
            parts.append(t.strip())
    return " / ".join(parts)


def extract(path, out):
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find("w:body", NS)
    lines = []
    for el in body:
        tag = el.tag.split("}")[1]
        if tag == "p":
            style = el.find("w:pPr/w:pStyle", NS)
            sid = style.get("{%s}val" % NS["w"]) if style is not None else ""
            text = "".join(n.text or "" for n in el.iter("{%s}t" % NS["w"])).strip()
            if not text:
                continue
            m = re.match(r"[Hh]eading(\d)", sid or "")
            if m:
                lines.append("#" * int(m.group(1)) + " " + text)
            else:
                lines.append(text)
        elif tag == "tbl":
            for tr in el.findall("w:tr", NS):
                cells = [cell_text(tc) for tc in tr.findall("w:tc", NS)]
                lines.append("| " + " | ".join(cells) + " |")
            lines.append("")
    io.open(out, "w", encoding="utf-8", newline="").write("\n".join(lines))
    print(out, len(lines), "lines")


if __name__ == "__main__":
    extract(sys.argv[1], sys.argv[2])
