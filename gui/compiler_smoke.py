"""Opt-in packaged WebView2 compiler acceptance using isolated invalid programs."""
import json
import sys
import traceback
import zipfile
from unittest.mock import patch
from gui.desktop_smoke import until
from gui.compiler_workspace import CompilerWorkspace


def run_smoke(app, report_path):
    report = {'passed': False, 'frozen': bool(getattr(sys, 'frozen', False)), 'checks': []}
    top = app.window.evaluate_js
    def js(source):
        return top('document.getElementById("wb-compiler-frame").contentWindow.eval(' + json.dumps(source) + ')')
    def check(label, condition):
        if not condition:
            raise AssertionError(label)
        report['checks'].append(label)
    try:
        if app.error:
            raise AssertionError(app.error)
        app.service.compiler = CompilerWorkspace(report_path.parent / 'jobs')
        until(lambda: top('!!window.MCUWorkbench'), 'workbench')
        top('window.MCUWorkbench.open("compiler")')
        until(lambda: js('!!window.MCUCompiler'), 'compiler page')
        check('未打开母本即可进入程序编译', app.service.session.editor is None)
        for name in ('broken1', 'broken2'):
            files = [[name + '.pln', 'bad'], ['pat/pin.dec', 'invalid_dec'], ['pat/a.pat', 'bad']]
            js('(()=>{const files=' + json.dumps(files) + '.map(([name,content])=>{const f=new File([content],name);'
               'Object.defineProperty(f,"webkitRelativePath",{value:' + json.dumps(name + '/') + '+name});return f;});'
               'window.MCUCompiler.addFolder(files).catch(e=>window.smokeError=String(e));})()')
            until(lambda: any(t['name'] == name and t['status'] == 'ready' for t in app.service.compiler.state()['tasks']), 'folder upload')
            until(lambda: js('!window.MCUCompiler.state().uploading'), 'upload completed')
        check('页面上传两个独立文件夹并识别Chroma', len(app.service.compiler.state()['tasks']) == 2)
        check('顶部Chroma显示四种编译模式', js('document.querySelector("select[data-platform=chroma]").options.length===4'))
        js('(()=>{const mode=document.querySelector("select[data-platform=chroma]");mode.value="dec";mode.dispatchEvent(new Event("change",{bubbles:true}));})()')
        js('document.getElementById("compiler-select-all").click();document.getElementById("compiler-start").click()')
        until(lambda: all(t['status'] == 'failed' for t in app.service.compiler.state()['tasks']), 'invalid program queue', 90)
        until(lambda: js('!window.MCUCompiler.state().running && window.MCUCompiler.state().tasks.every(t=>t.status==="failed")'), 'final UI')
        check('真实错误程序失败后继续第二项且页面显示终态', not app.service.compiler.state()['running'])
        check('队列使用顶部统一模式', [t.get('mode') for t in app.service.compiler.state()['tasks']] == ['dec', 'dec'])
        check('实际包呈现原始日志与诊断建议', js('document.getElementById("compiler-detail-body").textContent.includes("建议") && document.getElementById("compiler-log").textContent.length>30'))
        check('失败任务不能下载成功产物', js('document.getElementById("compiler-download-output").disabled'))
        top('window.MCUWorkbench.open("home");window.MCUWorkbench.open("compiler")')
        check('切换模块后编译任务仍保留', js('window.MCUCompiler.state().tasks.length===2'))
        # A synthetic successful result isolates the download path from vendor compilation.
        from webview.platforms import edgechromium
        task = next(iter(app.service.compiler.tasks.values()))
        archive = app.service.compiler.root / task['id'] / 'compiled.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as output:
            output.writestr('下载验证.txt', 'ZIP download acceptance')
        task['result']['outputAvailable'] = True
        task['status'] = 'passed'
        saved = report_path.parent / 'downloaded.zip'
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
            js('window.MCUCompiler.refresh()')
            until(lambda: js('!document.getElementById("compiler-download-output").disabled'), 'download enabled')
            js('document.getElementById("compiler-download-output").click()')
            until(lambda: saved.exists() and saved.read_bytes() == archive.read_bytes(), 'download saved ZIP', 12)
        check('点击输出触发原生保存并写入完整ZIP', bool(dialogs) and saved.read_bytes() == archive.read_bytes())
        report['downloadNames'] = dialogs
        js('document.getElementById("compiler-clear").click()')
        until(lambda: js('window.MCUCompiler.state().tasks.length===0'), 'clear history')
        check('清空列表保留ZIP且重载不恢复旧任务', archive.exists() and not CompilerWorkspace(app.service.compiler.root).state()['tasks'])
        js('''(()=>{
          const file=(name,content)=>({name,isFile:true,file:resolve=>resolve(new File([content],name))});
          const dir=(name,entries)=>({name,isDirectory:true,createReader:()=>{let done=false;return {readEntries:resolve=>{resolve(done?[]:entries);done=true;}};}});
          const roots=[dir('drop-one',[file('main.pln','plan'),dir('pat',[file('pin.dec','dec')])]),dir('drop-two',[file('main.prj','project')])];
          const event=new Event('drop',{bubbles:true,cancelable:true});
          Object.defineProperty(event,'dataTransfer',{value:{types:['Files'],items:roots.map(entry=>({kind:'file',webkitGetAsEntry:()=>entry}))}});
          document.getElementById('compiler-app').dispatchEvent(event);
        })()''')
        until(lambda: len(app.service.compiler.state()['tasks']) == 2 and all(t['status'] == 'ready' for t in app.service.compiler.state()['tasks']), 'drop folders uploaded')
        dropped = next(t for t in app.service.compiler.tasks.values() if t['name'] == 'drop-one')
        check('模拟拖入两个文件夹建立任务并保留子目录', (app.service.compiler.root / dropped['id'] / 'source/pat/pin.dec').read_bytes() == b'dec')
        report['tasks'] = app.service.compiler.state()['tasks']
        report['passed'] = True
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        app.window.destroy()
