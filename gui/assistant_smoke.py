"""Opt-in native two-window acceptance with fake model; no external network."""
import json
import sys
import time
import traceback

from gui.desktop_smoke import until


def run_smoke(app, report_path):
    report = {'passed': False, 'frozen': bool(getattr(sys, 'frozen', False)), 'checks': []}
    def check(label, condition):
        if not condition:
            raise AssertionError(label)
        report['checks'].append(label)
    top = app.window.evaluate_js
    def swd(script):
        return top('document.getElementById("wb-swd-frame").contentWindow.eval(' + json.dumps(script) + ')')
    try:
        if app.error:
            raise AssertionError(app.error)
        until(lambda: top('!!window.MCUWorkbench'), 'workbench')
        top('document.getElementById("wb-assistant").click()')
        until(lambda: app.bridge._assistant, 'assistant window')
        window = app.bridge._assistant
        js = window.evaluate_js
        until(lambda: js('!!document.getElementById("send") && !!window.pywebview'), 'assistant page')
        app.bridge.open_assistant()
        check('重复打开保持同一独立窗口', app.bridge._assistant is window)
        class HomeClient:
            def complete(self, messages, tools, cancel):
                if messages[-1]['role'] == 'tool':
                    return {'role': 'assistant', 'content': 'done'}
                return {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'home', 'type': 'function',
                    'function': {'name': 'prepare_swd', 'arguments': json.dumps({'request': {
                        'name': 'HomeCandidate', 'chip': 'py32f420', 'directives': [
                            {'kind': 'field_value', 'peri': 'RCC', 'reg': 'CFGR1', 'field': 'MCO2SEL', 'value': 2}]}})}}]}
        initial = app.bridge.assistant_context()
        check('首次首页生成时编辑器未加载', initial['swd'] == {})
        home = app.service.assistant.start({'requestId': 'home-stage', 'text': '首页独立配置', 'context': initial,
            'conditions': {'product': 'PCD009', 'platform': 'chroma', 'initialState': 'reset'}}, HomeClient(),
            materials=app.service.swd.materials().state())
        until(lambda: app.service.assistant.get(home['id'])['status'] == 'completed', 'home candidate')
        js('location.reload()')
        until(lambda: js('document.querySelectorAll("#history button").length===1'), 'home history')
        js('document.querySelector("#history button").click()')
        until(lambda: js('[...document.querySelectorAll("#candidates button")].some(b=>b.textContent==="送入 SWD 编辑器")'), 'home card')
        js('[...document.querySelectorAll("#candidates button")].find(b=>b.textContent==="送入 SWD 编辑器").click()')
        until(lambda: swd('!!window.MCUSWD && window.MCUSWD.state().pattern==="HomeCandidate"'), 'first editor apply')
        check('首页候选首次点击即可加载编辑器并送入', not app.service.swd.data['documents'])
        js('document.getElementById("undo").click()')
        until(lambda: swd('window.MCUSWD.state().documents.length===0'), 'undo home candidate')
        js('document.getElementById("new-task").click()')
        top('window.MCUWorkbench.open("swd")')
        until(lambda: swd('!!window.MCUSWD'), 'swd page')
        until(lambda: swd('!window.MCUSWD.state().busy'), 'swd ready')
        swd('document.getElementById("swd-create-pattern").click();document.getElementById("swd-new-pattern-name").value="NativeDraft";document.getElementById("swd-create-confirm").click()')
        until(lambda: swd('document.getElementById("swd-pattern-dialog").open'), 'pattern popup')
        swd('document.getElementById("swd-step-data").value="0x12345678";document.getElementById("swd-step-data").dispatchEvent(new Event("input",{bubbles:true}))')
        snapshot = app.bridge.assistant_context()
        check('上下文读取未保存弹窗行', snapshot['swd']['popupDraft']['rows'][0]['data'] == '0x12345678')
        check('读取未触发步骤保存', not app.service.swd.data['documents'])
        js('document.getElementById("settings-open").click()')
        until(lambda: js('document.getElementById("settings").open'), 'settings')
        js('document.getElementById("key").value="fake-native-key";document.getElementById("settings-save").click()')
        until(lambda: app.service.assistant_settings.state()['hasKey'], 'settings saved')
        check('密钥仅会话且未落明文', 'fake-native-key' not in app.service.assistant_settings.path.read_text())
        js('document.getElementById("settings-close").click()')
        from gui import assistant_model
        original = assistant_model.ModelClient.complete
        def fake(client, messages, tools, cancel, on_progress=None):
            time.sleep(.2)
            return {'role': 'assistant', 'content': '已读取弹窗草稿，未操作硬件。', 'reasoning_content': 'not visible'}
        assistant_model.ModelClient.complete = fake
        try:
            js('document.getElementById("prompt").value="解释当前草稿";document.getElementById("send").click()')
            until(lambda: js('document.getElementById("answer").textContent.includes("已读取弹窗")'), 'answer')
            check('真实JS桥接完成后台任务', len(app.service.assistant.list()) == 2)
            check('界面不展示推理原文', not js('document.body.textContent.includes("not visible")'))
            record = app.service.assistant.get(app.service.assistant.list()[0]['id'])
            check('任务冻结正确草稿', record['context']['swd']['popupDraft']['rows'][0]['data'] == '0x12345678')
            js('document.getElementById("prompt").value="继续解释";document.getElementById("send").click()')
            until(lambda: len(app.service.assistant.list()) == 3 and js('!document.getElementById("send").disabled'), 'followup')
            followup = app.service.assistant.get(app.service.assistant.list()[0]['id'])
            check('真实界面追问绑定上一任务', followup['parentId'] == record['id'])
            check('追问显示此前问答', js('document.getElementById("conversation").textContent.includes("解释当前草稿")'))
            swd('document.getElementById("swd-step-data").value="0xABC";document.getElementById("swd-step-data").dispatchEvent(new Event("input",{bubbles:true}))')
            check('回答期间主窗编辑保持可用', app.bridge.assistant_context()['swd']['popupDraft']['rows'][0]['data'] == '0xABC')
            # Discard this smoke fixture's unsaved draft by reloading only its frame.
            top('document.getElementById("wb-swd-frame").contentWindow.location.reload()')
            until(lambda: swd('!!window.MCUSWD && !document.getElementById("swd-pattern-dialog").open'), 'clean swd frame')
            def candidate_model(client, messages, tools, cancel, on_progress=None):
                if messages[-1]['role'] == 'tool':
                    return {'role': 'assistant', 'content': '独立候选已准备，未关联程序。'}
                arguments = {'request': {'name': 'NativeCandidate', 'chip': 'py32f420', 'directives': [
                    {'kind': 'field_value', 'peri': 'RCC', 'reg': 'CFGR1', 'field': 'MCO2SEL', 'value': 2}]}}
                return {'role': 'assistant', 'content': None, 'reasoning_content': 'private', 'tool_calls': [
                    {'id': 'fixture', 'type': 'function', 'function': {'name': 'prepare_swd', 'arguments': json.dumps(arguments)}}]}
            assistant_model.ModelClient.complete = candidate_model
            js('document.getElementById("new-task").click();document.getElementById("product").value="PT104";document.getElementById("platform").value="chroma";document.getElementById("reset").checked=true;document.getElementById("prompt").value="生成RCC候选";document.getElementById("send").click()')
            until(lambda: js('document.getElementById("candidates").children.length===1 && !document.getElementById("send").disabled'), 'candidate')
            js('[...document.querySelectorAll("#candidates button")].find(b=>b.textContent==="送入 SWD 编辑器").click()')
            until(lambda: swd('window.MCUSWD.state().pattern==="NativeCandidate"'), 'candidate draft')
            check('候选送入真实编辑器且未落盘', not app.service.swd.data['documents'])
            check('生成内容经真实工具到达编辑器', swd('window.MCUSWD.state().documents[0].rows[0].data==="0x02000000"'))
            js('document.getElementById("undo").click()')
            until(lambda: swd('window.MCUSWD.state().documents.length===0'), 'undo candidate')
            check('一次撤销完整恢复原编辑器', True)
            js('[...document.querySelectorAll("#candidates button")].find(b=>b.textContent==="送入 SWD 编辑器").click()')
            until(lambda: swd('window.MCUSWD.state().pattern==="NativeCandidate"'), 'reapply candidate')
            swd('document.getElementById("swd-edit-pattern").click()')
            until(lambda: swd('document.getElementById("swd-pattern-dialog").open'), 'edit popup')
            def edit_model(client, messages, tools, cancel, on_progress=None):
                if messages[-1]['role'] == 'tool':
                    return {'role': 'assistant', 'content': '字段修改候选已准备。'}
                arguments = {'operations': [{'rowIndex': 0, 'peripheral': 'RCC', 'register': 'CFGR1', 'field': 'MCO2SEL', 'value': 3}]}
                return {'role': 'assistant', 'content': None, 'reasoning_content': 'private', 'tool_calls': [
                    {'id': 'edit-fixture', 'type': 'function', 'function': {'name': 'prepare_swd_edit', 'arguments': json.dumps(arguments)}}]}
            assistant_model.ModelClient.complete = edit_model
            js('document.getElementById("new-task").click();document.getElementById("prompt").value="把当前第一行MCO2SEL改成3";document.getElementById("send").click()')
            until(lambda: js('[...document.querySelectorAll("#candidates button")].some(b=>b.textContent==="确认差异并应用到草稿")'), 'edit diff')
            check('修改前显示真实数值差异', js('document.getElementById("candidates").textContent.includes("0x02000000 → 0x03000000")'))
            js('[...document.querySelectorAll("#candidates button")].find(b=>b.textContent==="确认差异并应用到草稿").click()')
            until(lambda: swd('document.getElementById("swd-step-data").value==="0x03000000"'), 'apply edit')
            check('修改作用于未保存弹窗且不写原文档', swd('window.MCUSWD.state().documents[0].rows[0].data==="0x02000000"'))
            js('document.getElementById("undo").click()')
            until(lambda: swd('document.getElementById("swd-step-data").value==="0x02000000"'), 'undo edit')
            check('字段修改整批撤销恢复原弹窗', True)
            # A later user edit must make the old candidate inapplicable.
            swd('document.getElementById("swd-pin-swc").value="PA12";document.getElementById("swd-pin-swc").dispatchEvent(new Event("input",{bubbles:true}))')
            js('[...document.querySelectorAll("#candidates button")].find(b=>b.textContent==="确认差异并应用到草稿").click()')
            until(lambda: js('document.getElementById("error").textContent.includes("草稿已改变")'), 'stale refusal')
            check('用户改动后拒绝旧候选', swd('document.getElementById("swd-step-data").value==="0x02000000"'))
            top('window.MCUWorkbench.open("hex")')
            def hexjs(script):
                return top('document.getElementById("wb-hex-frame").contentWindow.eval(' + json.dumps(script) + ')')
            until(lambda: hexjs('!!window.MCUHex && window.MCUHex.state().profiles.length>0'), 'hex ready')
            hexjs('document.getElementById("hex-chip").value="PT100";document.getElementById("hex-chip").dispatchEvent(new Event("change"));document.getElementById("hex-profile").value="swd-sram-pt100";document.getElementById("hex-profile").dispatchEvent(new Event("change"))')
            hex_task = app.service.hex.add_input(b':0400000001020304F2\n:00000001FF\n', 'assistant-smoke.hex')
            hexjs('window.MCUHex.refresh()')
            until(lambda: hexjs('window.MCUHex.state().tasks.length===1'), 'hex uploaded')
            hexjs('document.getElementById("hex-select-all").click()')
            def action_model(client, messages, tools, cancel, on_progress=None):
                if messages[-1]['role'] == 'tool':
                    return {'role': 'assistant', 'content': '转换参数已准备，请确认。'}
                return {'role': 'assistant', 'content': None, 'tool_calls': [
                    {'id': 'action', 'type': 'function', 'function': {'name': 'prepare_workbench_action',
                      'arguments': '{"operation":"hex"}'}}]}
            assistant_model.ModelClient.complete = action_model
            js('document.getElementById("new-task").click();document.getElementById("prompt").value="按当前参数转换HEX";document.getElementById("send").click()')
            until(lambda: js('[...document.querySelectorAll("#candidates button")].some(b=>b.textContent==="确认参数并启动") && !document.getElementById("send").disabled'), 'action card')
            check('转换候选确认前未启动', app.service.hex.tasks[hex_task['id']]['status'] == 'ready')
            js('[...document.querySelectorAll("#candidates button")].find(b=>b.textContent==="确认参数并启动").click()')
            until(lambda: app.service.hex.tasks[hex_task['id']]['status'] == 'completed', 'real hex conversion')
            check('助手确认执行真实HEX转换并可下载', app.service.hex.download(hex_task['id']).is_file())
            def probe_model(client, messages, tools, cancel, on_progress=None):
                if messages[-1]['role'] == 'tool':
                    return {'role': 'assistant', 'content': '连接工具往返通过。'}
                return {'role': 'assistant', 'content': None, 'tool_calls': [
                    {'id': 'probe', 'type': 'function', 'function': {'name': 'connection_probe', 'arguments': '{}'}}]}
            assistant_model.ModelClient.complete = probe_model
            js('document.getElementById("settings-open").click()')
            until(lambda: js('document.getElementById("settings").open'), 'probe settings')
            js('document.getElementById("connection-test").click()')
            until(lambda: js('document.getElementById("answer").textContent.includes("连接工具往返通过")'), 'probe roundtrip')
            check('设置窗口完成工具往返测试', True)
            import threading
            entered, release = threading.Event(), threading.Event()
            def slow_model(*args, **kwargs):
                entered.set(); release.wait(10)
                return {'role': 'assistant', 'content': 'late response must be discarded'}
            assistant_model.ModelClient.complete = slow_model
            js('document.getElementById("new-task").click();document.getElementById("prompt").value="取消测试";document.getElementById("send").click()')
            until(lambda: entered.is_set() and js('!document.getElementById("cancel").disabled'), 'slow model entered')
            js('document.getElementById("cancel").click()')
            until(lambda: js('document.getElementById("stage").textContent.includes("cancelled")'), 'cancelled')
            release.set(); time.sleep(.3)
            check('取消后迟到回答未提交', not js('document.body.textContent.includes("late response")'))
            def missing_reset_model(client, messages, tools, cancel, on_progress=None):
                request = {'name': 'PA4_MCO', 'chip': 'py32f420', 'directives': [
                    {'kind': 'field_value', 'peri': 'RCC', 'reg': 'CFGR1', 'field': 'MCO2SEL', 'value': 2},
                    {'kind': 'field_value', 'peri': 'RCC', 'reg': 'CFGR1', 'field': 'MCO2PRE', 'value': 14},
                    {'kind': 'clk_enable', 'periph': 'GPIOA'},
                    {'kind': 'pin_config', 'pin': 'PA4', 'func': 'MCO2'}]}
                return {'role': 'assistant', 'content': None, 'tool_calls': [
                    {'id': 'reset', 'type': 'function', 'function': {'name': 'prepare_swd',
                     'arguments': json.dumps({'request': request})}}]}
            assistant_model.ModelClient.complete = missing_reset_model
            js('document.getElementById("new-task").click();document.getElementById("product").value="PCD009";document.getElementById("reset").checked=true;document.getElementById("prompt").value="PA4 MCO HSI8M /128";document.getElementById("send").click()')
            until(lambda: js('!!document.querySelector("#candidates form input")'), 'knowledge question')
            check('缺资料显示指定寄存器询问卡', js('document.getElementById("candidates").textContent.includes("GPIOA.AFRL")'))
            js('document.querySelector("#candidates form input").value="全0";document.querySelector("#candidates form button").click()')
            until(lambda: js('document.getElementById("answer").textContent.includes("独立Excel与Pattern已生成")'), 'knowledge retry')
            check('用户补充后原PA4配置完整生成', len(app.service.assistant.get(app.service.assistant.list()[0]['id'])['candidates'][0]['rows']) == 7)
            check('知识持久化并显示用户来源', (app.service.assistant.root / 'reset-confirmations.json').is_file() and js('document.getElementById("answer").textContent.includes("用户工程确认")'))
        finally:
            assistant_model.ModelClient.complete = original
        window.destroy()
        until(lambda: app.bridge._assistant is None, 'assistant closed')
        app.bridge.open_assistant()
        until(lambda: app.bridge._assistant.evaluate_js('document.getElementById("history").children.length===9'), 'history reopened')
        check('助手关闭重开保留历史', True)
        report['passed'] = True
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        app.window.destroy()
