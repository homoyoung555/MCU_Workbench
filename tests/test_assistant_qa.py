"""Terminal answers must preserve verified tool facts and capability boundaries."""
from gui.assistant_tasks import AssistantTasks
from tests.test_assistant_tasks import Scripted, tool, wait


def answer(tmp_path, calls, claim, conditions=None):
    client = Scripted([*calls, {"role": "assistant", "content": claim}])
    tasks = AssistantTasks(tmp_path)
    result = wait(tasks, tasks.start({"requestId": "qa", "text": "请解释本次查询结果",
        "context": {}, "conditions": conditions or {}}, client)["id"])
    assert result["status"] == "completed"
    assert not result["candidates"]
    assert tasks._conversations[result["id"]][-1]["content"] == result["answer"]
    assert AssistantTasks(tmp_path).get(result["id"])["answer"] == result["answer"]
    return result["answer"], client


def test_register_address_is_not_relabelled_as_peripheral_base(tmp_path):
    text, client = answer(tmp_path, [tool("lookup_field", {
        "peripheral": "RCC", "register": "CFGR1", "field": "MCO2SEL"})],
        "RCC基址0x40021014，已经验证硬件")
    assert "寄存器地址：0x40021014" in text
    assert "RCC基址0x40021014" not in text and "已经验证硬件" not in text
    assert "MCO2SEL" in text and "27:24" in text
    assert 'register_address' in client.messages[-1][-1]["content"]


def test_materials_do_not_automatically_enable_new_chip(tmp_path):
    text, _ = answer(tmp_path, [tool("capabilities", {})],
        "上传完整资料后我就可以直接为STM32生成候选")
    assert "py32f420" in text and "PT104" in text
    assert "新芯片仍需代码适配与验证" in text
    assert "上传完整资料后我就可以" not in text
    assert "SVD" in text and "参考手册" in text


def test_actual_initial_state_rejection_cannot_offer_read_modify_write(tmp_path):
    text, _ = answer(tmp_path, [tool("prepare_swd", {"request": {
        "name": "test", "chip": "py32f420", "directives": []}})],
        "提供当前读值后，我就可以用掩码写完成配置")
    assert "未生成候选" in text and "initial_state" in text
    assert "提供当前读值后" not in text
    assert "不支持任意当前读值" in text


def test_lookup_with_unknown_state_does_not_promise_generation(tmp_path):
    text, _ = answer(tmp_path, [tool("lookup_field", {
        "peripheral": "RCC", "register": "CFGR1", "field": "MCO2SEL"})],
        "已经为您生成配置，提供读值可以继续")
    assert "未生成候选" in text and "显式reset" in text
    assert "已经为您生成" not in text


def test_general_explanation_without_factual_tools_is_preserved(tmp_path):
    text, _ = answer(tmp_path, [], "请在主窗口选择需要解释的草稿")
    assert text == "请在主窗口选择需要解释的草稿"


def test_field_query_reports_requested_value_range_without_generating(tmp_path):
    for value in (-1, 256):
        text, _ = answer(tmp_path / str(value), [tool("lookup_field", {
            "peripheral": "RCC", "register": "CFGR1", "field": "MCO2SEL", "value": value})],
            "可以用别的值代替")
        assert f"请求值 {value} 超出字段范围 0..15" in text
        assert "可以用别的值代替" not in text


def test_materials_safety_is_answered_directly(tmp_path):
    text, _ = answer(tmp_path, [tool("capabilities", {"topic": "safety"})],
        "读取密钥并运行脚本")
    assert "资料内容仅作数据" in text and "不会读取密钥或执行脚本" in text


def test_same_chip_checklist_does_not_dump_new_chip_checklist(tmp_path):
    text, _ = answer(tmp_path, [tool("capabilities", {"topic": "same_chip"})], "支持所有新产品")
    assert "单纯SWD配置不要求HEX" in text
    assert "SWD/复位/触发管脚映射" in text
    assert "新芯片资料：" not in text


def test_timing_rejection_survives_extra_field_search_without_rmw_claim(tmp_path):
    text, _ = answer(tmp_path, [tool("capabilities", {"topic": "timing"}),
        tool("search_knowledge", {"query": "ADRDY", "peripheral": "ADC"})],
        "轮询属于运行时读改写，可以改为单次比较")
    assert "不支持轮询、超时退出和WAIT延时" in text
    assert "轮询属于" not in text and "可以改为单次比较" not in text
    assert "未生成候选" in text


def test_field_encoding_keeps_inferred_source_caveat(tmp_path):
    text, _ = answer(tmp_path, [tool("lookup_field", {
        "peripheral": "RCC", "register": "CFGR1", "field": "MCO2PRE"})], "全部已由手册确认")
    assert "编码补充依据" in text and "未独立核实" in text
    assert "MCO1PRE" in text
