"""Excel -> ATE 测试程序生成器统一入口。

V1.4 的源码树不承载母本、Pattern、编译器或生成物。所有运行数据都从
显式 ``--workspace``（或 ``V14_WORKSPACE``）注入。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


SOURCE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SOURCE_ROOT))

from program_gen.compiler import ProductCompiler
from program_gen.generation_service import GenerationService
from program_gen.request_factory import GenerationRoots
from program_gen.workbook import WorkbookReader
from program_gen.workspace import WorkspaceLayout, WorkspaceLayoutError


def main(argv=None):
    parser = argparse.ArgumentParser(description="Excel -> ATE 测试程序生成器")
    parser.add_argument("--platform", required=True, choices=["s100", "chroma"])
    parser.add_argument(
        "--workspace",
        default=os.environ.get("MCU_WORKBENCH_WORKSPACE") or os.environ.get("V14_WORKSPACE") or str(SOURCE_ROOT.parent / "MCU_Workbench_WORKSPACE"),
        help="外部运行资料根目录；优先 MCU_WORKBENCH_WORKSPACE，兼容 V14_WORKSPACE",
    )
    parser.add_argument(
        "--skip-check",
        action="store_true",
        help="开发模式：跳过 preflight 展示；不能绕过 ProductCompiler ERROR",
    )
    parser.add_argument(
        "--master",
        default=None,
        help="input/workbook 下的文件名；不填则按文件名确定性选择第一个母本",
    )
    parser.add_argument("--cp", default=None, choices=["CP1", "CP2", "CP3"])
    parser.add_argument(
        "--variant", default=None, choices=["lab", "production", "both"]
    )
    parser.add_argument(
        "--allow-stub-publication",
        action="store_true",
        help="显式允许发布含 STUB 资源的已验证产物；其他 blocker 仍会阻断",
    )
    args = parser.parse_args(argv)

    if not args.workspace:
        parser.error("必须用 --workspace 或 V14_WORKSPACE 指定外部运行工作区")
    try:
        layout = WorkspaceLayout(args.workspace, source_root=SOURCE_ROOT)
        master = layout.find_master(args.master)
    except WorkspaceLayoutError as exc:
        parser.error(str(exc))
    if master is None:
        parser.error("未在 workspace/input/workbook 找到母本")

    workbook_model = WorkbookReader().read(str(master.resolve()))
    product_compilation = ProductCompiler().compile(workbook_model)

    if not args.skip_check:
        from preflight import PreflightError, check_master

        try:
            check_master(product_compilation, gate=True)
        except PreflightError:
            print("\n[gate] 产品编译存在 ERROR，已中止生成。修正母本后重跑。")
            return 2
    elif not product_compilation.is_valid:
        from preflight import check_master

        check_master(product_compilation, verbose=True)
        print("\n[gate] ProductCompilation 无效；--skip-check 不能绕过编译错误。")
        return 2

    roots, platform_roots = _generation_roots(layout)
    result = GenerationService().execute(
        workbook_model,
        product_compilation,
        roots,
        tools_root=SOURCE_ROOT / "tools",
        toolchain_roots={
            "chroma": layout.toolchain("chroma"),
            "s100": layout.toolchain("s100"),
        },
        platform_roots=platform_roots,
        platforms=(args.platform,),
        cps=(args.cp,) if args.cp else ("CP1", "CP2", "CP3"),
        variants=(args.variant,) if args.variant not in (None, "both") else (
            "lab",
            "production",
        ),
        allow_stub_publication=args.allow_stub_publication,
    )
    _print_orchestration_result(result)
    return 0 if result.published else 1


def _generation_roots(layout: WorkspaceLayout):
    return (
        GenerationRoots(
            output_root=layout.root / "outputs",
            chroma=layout.platform_output("chroma"),
            s100=layout.platform_output("s100"),
        ),
        {
            "chroma": layout.platform_input("chroma"),
            "s100": layout.platform_input("s100"),
        },
    )


def _print_orchestration_result(result):
    print(
        f"[generation] status={result.status.value} "
        f"request={result.request_identity}"
    )
    for target in result.targets:
        print(
            f"[target] {target.target.identity} "
            f"validation={'PASS' if target.validation_passed else 'BLOCKED'} "
            f"manifest={target.manifest_identity or '-'} "
            f"evidence={target.validation_identity or '-'} "
            f"error={target.error or '-'}"
        )
    if result.error:
        print(f"[generation] error={result.error}")


if __name__ == "__main__":
    raise SystemExit(main())
