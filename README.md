# MCU Workbench V0.5

独立 MCU 工作台试用版：程序编辑与生成、SCAN 转换、SWD 生成、HEX 转 Pattern、独立 AI 助手。
V0.5 程序编译暂未开放，界面和服务端均禁用；发布包不含 Chroma/S100 工具链。不连接硬件。

## 另一台电脑使用

1. 从私有仓库的 Releases 下载程序包和工程资料包，解压到同一个目录。
2. 保持 MCU_Workbench/ 与 MCU_Workbench_WORKSPACE/ 并列，双击 MCU_Workbench/启动工作台.cmd。
3. 若窗口无法启动，安装 Microsoft Edge WebView2 Evergreen Runtime：https://developer.microsoft.com/en-us/microsoft-edge/webview2/ 。EXE 包自带 Python，无须另装。
4. 打开程序 Excel 时，选择 MCU_Workbench_WORKSPACE/input/workbook/ 下的所需文件。资料包保留源文件，不自动修正业务配置。
5. AI 助手首次使用需要在“模型设置”中填写自己的 API，并测试连接。旧电脑的加密设置、聊天历史和密钥不随发布迁移。

完整解压结构：

```text
部署目录/
  MCU_Workbench/
    启动工作台.cmd
    MCU_Workbench_App/MCU_Workbench_App.exe
    MCU_Workbench_App/_internal/...
    docs/assistant-guide.html
  MCU_Workbench_WORKSPACE/input/...
```

启动脚本使用相邻资料目录；不要仅复制 EXE。更换资料目录可设置 MCU_WORKBENCH_WORKSPACE。
生成结果位于资料目录 outputs/gui_runs/；程序和数据分别升级，保留自己的运行资料。

## 源码开发和打包

建议 Python 3.12。安装核心依赖：`python -m pip install -r requirements.txt`。
桌面开发/打包另安装：`python -m pip install -r requirements-desktop.txt`。
桌面入口 `python gui/desktop.py`；浏览器开发 `python gui/server.py --port 8844`，访问 http://127.0.0.1:8844/ 。
打包 `python gui/build_desktop.py --distpath .scratch/build-v05/dist --buildpath .scratch/build-v05/build`。
发布时必须保留完整 MCU_Workbench_App/ 和 _internal/。内置知识在 gui/data/ 与 swd_authoring/data/，后者 data/cache/ 也是必需运行知识。

## 验证与试用边界

安装 pytest 后运行 `python -B -m pytest -q -p no:cacheprovider tests/test_v05_release.py tests/test_compiler_http.py tests/test_workbench_paths.py tests/test_gui_desktop.py tests/test_firmware_sram.py`。
前端检查需要 Node.js：`node tests/test_gui_workbench.cjs`、`node tests/swd_ui_contract.cjs`。

试用版未完成另一台电脑或硬件验收，不能把源码生成成功当作上机通过。
既有全仓回归仍有 26 项领域/母本基线差异及 3 项环境跳过，详见发布说明。
TK SRAM 示例需要真实 sram_capture.pat；占位文件不能用于正式程序，源 Excel 的待修配置需用户确认。
Kimi K3 在此前账号测试中未连接成功，模型是否可调用取决于所填账号的接口和权限；不附带任何 API 密钥。

## 发布内容

源码仓库保留代码、内置知识、测试、说明；Release 提供程序 ZIP 与工程资料 ZIP。
工具链、临时证据、日志、历史聊天、输出和用户设置不提交。工程资料应保存在私有仓库的 Release 中。
