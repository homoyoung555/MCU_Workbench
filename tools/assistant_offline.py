"""Offline authoring gate: JSON intent → existing SWD Excel → platform text.

Run ``python -m tools.assistant_offline --help``. No model or hardware access.
"""
import argparse
import json
from pathlib import Path

from gui.assistant_swd import prepare_candidate


def main():
    parser = argparse.ArgumentParser(description='离线配置编译；仅生成独立文件，不修改工作台工程或Link。')
    parser.add_argument('--request', type=Path, required=True, help='配置意图JSON文件')
    parser.add_argument('--platform', choices=('chroma', 's100'), required=True)
    parser.add_argument('--product', choices=('PT104', 'PCD009'), required=True)
    parser.add_argument('--initial-state', choices=('reset',), required=True,
                        help='确认流程运行前满足复位初始条件；本工具不会执行硬件复位')
    parser.add_argument('--output', type=Path, required=True, help='新的输出目录；存在时拒绝覆盖')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('输出目录已存在，请选择新目录；不覆盖已有文件')
    payload = json.loads(args.request.read_text(encoding='utf-8-sig'))
    artifact = prepare_candidate(payload, product_profile_id=args.product,
                                 platform=args.platform, initial_state=args.initial_state)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'configuration.xlsx').write_bytes(artifact.pop('excel'))
    suffix = '.pat' if args.platform == 'chroma' else '.sd'
    (args.output / (payload['name'] + suffix)).write_bytes(artifact.pop('pattern'))
    (args.output / 'validation.json').write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(args.output.resolve()), 'validation': artifact['validation']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
