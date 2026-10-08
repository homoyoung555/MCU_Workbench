# 机械重构辅助工具：
#   analyze  —— 报告每个函数引用了哪些模块级全局数据名（不含函数名/导入名）
#   rewrite  —— 把这些引用改写为 G.<name>，并移除函数内的 global 声明
# 用法:
#   python g_rewrite.py analyze <file.py> > shared.json
#   python g_rewrite.py rewrite <file.py> <shared.json>
import ast
import io
import json
import symtable
import sys


def load(src_path):
    return io.open(src_path, encoding="utf-8", newline="").read()


def module_data_names(tree):
    """模块层被绑定的数据名（剔除函数名与 import 别名），含函数内 global 声明的名字。"""
    bound, funcs, imports = set(), set(), set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            funcs.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                imports.add(a.asname or a.name.split(".")[0])
        else:
            for n in ast.walk(node):
                if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                    bound.add(n.id)
    for n in ast.walk(tree):
        if isinstance(n, ast.Global):
            bound.update(n.names)
    return (bound - funcs - imports), funcs, imports


def analyze(src_path):
    src = load(src_path)
    tree = ast.parse(src)
    data_names, funcs, imports = module_data_names(tree)
    st = symtable.symtable(src, src_path, "exec")
    refs = {}

    def walk(scope):
        if scope.get_type() == "function":
            for sym in scope.get_symbols():
                nm = sym.get_name()
                if nm in data_names and sym.is_global():
                    refs.setdefault(nm, []).append(scope.get_name())
        for ch in scope.get_children():
            walk(ch)

    walk(st)
    report = {
        "shared": sorted(refs),                  # 函数引用到的全局数据名
        "module_only": sorted(data_names - set(refs)),  # 只在模块层使用的数据名
        "by_name": {k: sorted(set(v)) for k, v in sorted(refs.items())},
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))


SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
               ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)


def match_children(scope, node):
    """把 ast 作用域子节点与 symtable 子作用域按 (行号) 配对。"""
    pairs = {}
    children = list(scope.get_children())
    for ch in children:
        pairs.setdefault(ch.get_lineno(), []).append(ch)
    return pairs


def rewrite(src_path, shared_path):
    src = load(src_path)
    shared = set(json.load(io.open(shared_path, encoding="utf-8"))["shared"])
    tree = ast.parse(src)
    st = symtable.symtable(src, src_path, "exec")

    edits = []      # (lineno, byte_col) 处插入 b"G."
    removals = []   # global 语句 (lineno, col, end_lineno, end_col)

    def visit(node, scope):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, SCOPE_NODES):
                # 装饰器与参数默认值在外层作用域求值
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for d in child.decorator_list:
                        visit_expr(d, scope)
                    for d in child.args.defaults + [x for x in child.args.kw_defaults if x]:
                        visit_expr(d, scope)
                sub = find_scope(scope, child)
                if sub is None:
                    # 3.12+ 列表/集合/字典推导式内联：无独立作用域，沿用当前作用域
                    visit(child, scope)
                else:
                    body = child.body if hasattr(child, "body") else child
                    visit(child, sub) if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        else visit_funcbody(child, sub)
            elif isinstance(child, ast.Global):
                removals.append((child.lineno, child.col_offset,
                                 child.end_lineno, child.end_col_offset))
            elif isinstance(child, ast.Name):
                handle_name(child, scope)
                visit(child, scope)
            else:
                visit(child, scope)

    def visit_funcbody(fnode, scope):
        for stmt in fnode.body:
            visit(stmt, scope)

    def visit_expr(expr, scope):
        if isinstance(expr, ast.Name):
            handle_name(expr, scope)
        for child in ast.iter_child_nodes(expr):
            visit_expr(child, scope)

    def handle_name(nd, scope):
        if nd.id not in shared:
            return
        if scope.get_type() != "module":
            try:
                sym = scope.lookup(nd.id)
            except KeyError:
                return
            if sym.is_local() or sym.is_parameter() or sym.is_free():
                if not sym.is_declared_global():
                    return
        edits.append((nd.lineno, nd.col_offset))

    def find_scope(scope, node):
        want = getattr(node, "name", None)
        if want is None:
            want = {ast.Lambda: "lambda", ast.GeneratorExp: "genexpr",
                    ast.ListComp: "listcomp", ast.SetComp: "setcomp",
                    ast.DictComp: "dictcomp"}.get(type(node))
        for ch in scope.get_children():
            if ch.get_lineno() == node.lineno and (want is None or ch.get_name() == want):
                return ch
        return None

    visit(tree, st)

    lines = src.split("\n")
    # 行内多个编辑从右往左；col_offset 是 UTF-8 字节偏移
    by_line = {}
    for ln, col in set(edits):
        by_line.setdefault(ln, []).append(col)
    for ln, cols in by_line.items():
        raw = lines[ln - 1].encode("utf-8")
        for col in sorted(cols, reverse=True):
            raw = raw[:col] + b"G." + raw[col:]
        lines[ln - 1] = raw.decode("utf-8")
    # global 语句整条替换为 pass（保持缩进；均为单行语句）
    for ln, col, eln, ecol in removals:
        assert ln == eln, f"global 语句跨行: line {ln}"
        raw = lines[ln - 1].encode("utf-8")
        lines[ln - 1] = (raw[:col] + b"pass  # (global -> G.*)").decode("utf-8")

    io.open(src_path, "w", encoding="utf-8", newline="").write("\n".join(lines))
    print(f"rewrote {len(set(edits))} name refs, removed {len(removals)} global stmts")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "analyze":
        analyze(sys.argv[2])
    elif cmd == "rewrite":
        rewrite(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit("usage: g_rewrite.py analyze|rewrite ...")
