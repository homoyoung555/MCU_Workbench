# 把 chroma 产物变更分为两类：仅注释变化 vs 功能性变化（剥离 // 注释后仍有差异）。
# 对功能性变化的文件输出剥离注释后的 unified diff 摘要。
import difflib
import io
import re
import subprocess

ROOT = r"F:\01_work\99_Claude\06_Chroma_MCU_program\V1.1"


def strip_comments(text):
    lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        line = re.sub(r"//.*$", "", line).rstrip()
        lines.append(line)
    return lines


changed = subprocess.run(["git", "-c", "core.quotepath=false", "diff", "--name-only", "--", "Chroma_program"],
                         capture_output=True, text=True, encoding="utf-8", cwd=ROOT).stdout.split()
comment_only, functional = [], {}
for fp in changed:
    old = subprocess.run(["git", "show", "HEAD:" + fp], capture_output=True, cwd=ROOT).stdout.decode("utf-8", "replace")
    new = io.open(ROOT + "\\" + fp.replace("/", "\\"), encoding="utf-8", errors="replace").read()
    o, n = strip_comments(old), strip_comments(new)
    if o == n:
        comment_only.append(fp)
    else:
        diff = list(difflib.unified_diff(o, n, lineterm="", n=0))
        functional[fp] = diff

print(f"仅注释变化: {len(comment_only)} 个文件")
print(f"功能性变化: {len(functional)} 个文件")
out = ["# Chroma 同步产物差异报告（剥离注释后）", "",
       f"- 仅注释富化（寄存器字段说明）: {len(comment_only)} 个文件",
       f"- 功能性变化: {len(functional)} 个文件", ""]
for fp, diff in functional.items():
    adds = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
    dels = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
    out.append(f"## {fp}  (+{adds}/-{dels})")
    out.append("```diff")
    out.extend(diff[:120])
    if len(diff) > 120:
        out.append(f"...（共 {len(diff)} 行 diff，截断）")
    out.append("```")
    out.append("")
io.open(ROOT + r"\Day4产物差异报告.md", "w", encoding="utf-8", newline="").write("\n".join(out))
print("report -> Day4产物差异报告.md")
