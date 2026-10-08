"""Opt-in native HEX conversion and ZIP download acceptance."""
import json
import sys
import traceback
import zipfile
from unittest.mock import patch
from gui.desktop_smoke import until
from gui.hex_workspace import HexWorkspace


def run_smoke(app, report_path):
    report = {'passed': False, 'frozen': bool(getattr(sys, 'frozen', False)), 'checks': []}
    top = app.window.evaluate_js
    def js(source):
        return top('document.getElementById("wb-hex-frame").contentWindow.eval(' + json.dumps(source) + ')')
    def check(label, condition):
        if not condition:
            raise AssertionError(label)
        report['checks'].append(label)
    try:
        app.service.hex = HexWorkspace(report_path.parent / 'jobs')
        until(lambda: top('!!window.MCUWorkbench'), 'workbench')
        top('window.MCUWorkbench.open("hex")')
        until(lambda: js('!!window.MCUHex && window.MCUHex.state().profiles.length===42'), 'HEX catalog')
        check('无需打开Excel即可选择全部42个版本', app.service.session.editor is None)
        js('(()=>{const s=document.getElementById("hex-chip");s.value="PT100";s.dispatchEvent(new Event("change"));const p=document.getElementById("hex-profile");p.value="swd-sram-pt100";p.dispatchEvent(new Event("change"));})()')
        check('选择产品后预填C#默认管脚', js('JSON.stringify(Array.from(document.querySelectorAll("[data-pin-index]"),e=>e.value))===JSON.stringify(["PA14","PA13","NRST"])'))
        js('(()=>{const s=document.getElementById("hex-output-platform");s.value="both";s.dispatchEvent(new Event("change"));})()')
        raw = ':10000000000102030405060708090A0B0C0D0E0F78\n:00000001FF\n'
        js('(()=>{const dt=new DataTransfer();dt.items.add(new File(['+json.dumps(raw)+'],"固件一.hex"));dt.items.add(new File(['+json.dumps(raw)+'],"固件二.hex"));document.getElementById("hex-app").dispatchEvent(new DragEvent("drop",{bubbles:true,cancelable:true,dataTransfer:dt}));})()')
        until(lambda: js('window.MCUHex.state().tasks.length===2 && !window.MCUHex.state().uploading'), 'upload')
        check('拖入多个HEX建立独立任务', len(app.service.hex.state()['tasks']) == 2)
        check('上传后型号选择仍可操作', js('!document.getElementById("hex-chip").disabled'))
        js('document.querySelectorAll("[data-pin-index]").forEach((input,i)=>{input.value=["CLK","DATA","RST"][i];input.dispatchEvent(new Event("input"));});document.getElementById("hex-verify").click()')
        js('document.getElementById("hex-reset-pins").click()')
        check('恢复默认管脚保留校验开关', js('document.querySelector("[data-pin-index]").value==="PA14" && !document.getElementById("hex-verify").checked'))
        js('document.querySelectorAll("[data-pin-index]").forEach((input,i)=>{input.value=["CLK","DATA","RST"][i];input.dispatchEvent(new Event("input"));})')
        js('window.MCUHex.refresh()')
        until(lambda: js('document.querySelector("[data-pin-index]").value==="CLK"'), 'pin draft')
        check('刷新保留管脚修改与校验关闭', js('!document.getElementById("hex-verify").checked'))
        js('document.getElementById("hex-select-all").click();document.getElementById("hex-start").click()')
        until(lambda: js('window.MCUHex.state().tasks.every(t=>t.status==="completed")'), 'conversion', 40)
        check('串行转换两份HEX并保留所选版本', all(t['profileId']=='swd-sram-pt100' for t in app.service.hex.state()['tasks']))
        check('完成后型号选择仍可操作', js('!document.getElementById("hex-chip").disabled'))
        check('实际任务冻结管脚与校验设置', all(t['profile']['pins']==['CLK','DATA','RST'] and not t['profile']['verify'] for t in app.service.hex.state()['tasks']))
        js('document.querySelector("[data-preview-file]").click()')
        until(lambda: js('document.querySelector(".hex-preview").textContent.includes("SPM_PATTERN")'), 'PAT preview')
        check('结果文件预览使用修改后的管脚', js('document.querySelector(".hex-preview").textContent.includes("CLK,DATA,RST;")'))
        js('Array.from(document.querySelectorAll("[data-preview-file]")).find(e=>e.dataset.previewFile.endsWith(".sd")).click()')
        until(lambda: js('document.querySelector(".hex-preview").textContent.includes("TIMING_SET G1_2")'), 'SD preview')
        check('双格式输出且SD使用所选管脚和对应时序', js('document.querySelector(".hex-preview").textContent.includes("CLK,DATA,RST;")'))
        check('页面没有横向溢出', js('document.documentElement.scrollWidth<=window.innerWidth'))
        from webview.platforms import edgechromium
        saved = report_path.parent/'downloaded.zip'
        dialogs = []
        class SaveDialog:
            def ShowDialog(self, owner):
                dialogs.append(self.FileName)
                self.FileName = str(saved)
                return edgechromium.WinForms.DialogResult.OK
        native_forms = edgechromium.WinForms
        class DownloadForms:
            SaveFileDialog = SaveDialog
            def __getattr__(self, name):
                return getattr(native_forms, name)
        with patch.object(edgechromium, 'WinForms', DownloadForms()):
            js('document.getElementById("hex-download").click()')
            until(lambda: saved.exists() and zipfile.is_zipfile(saved), 'native ZIP download', 12)
        with zipfile.ZipFile(saved) as archive:
            check('原生保存ZIP包含真实PAT与转换摘要', bool(dialogs) and 'conversion.json' in archive.namelist() and any(n.endswith('.pat') for n in archive.namelist()) and any(n.endswith('.sd') for n in archive.namelist()))
        outputs = list(app.service.hex.root.rglob('*.pat'))
        js('document.getElementById("hex-clear").click()')
        until(lambda: js('window.MCUHex.state().tasks.length===0'), 'clear')
        check('清空历史保留磁盘产物且重载不恢复', bool(outputs) and all(p.exists() for p in outputs) and not HexWorkspace(app.service.hex.root).state()['tasks'])
        report['passed'] = True
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        app.window.destroy()
