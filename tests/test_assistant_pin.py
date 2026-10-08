import json
from gui.assistant_tasks import AssistantTasks, TOOLS
from tests.test_assistant_tasks import Scripted, tool, wait


def run(tmp_path, calls):
    client = Scripted([*calls, {"role": "assistant", "content": "已经生成完整PA4流程"}])
    tasks = AssistantTasks(tmp_path)
    result = wait(tasks, tasks.start({"requestId": "pa4", "text": "PA4作为MCO输出HSI8M的128分频",
        "context": {}, "conditions": {"product": "PCD009", "platform": "chroma", "initialState": "reset"}}, client)["id"])
    return result, client


def test_pa4_iomux_is_reachable_through_public_assistant_tools(tmp_path):
    result, client = run(tmp_path, [tool("lookup_pin", {"pin": "PA4"})])
    returned = json.loads(client.messages[1][-1]["content"])
    assert returned["pin"]["alternate_functions"]["AF0"] == "MCO2"
    assert returned["pin"]["pin_name"] == "PA04"
    assert "未生成候选" in result["answer"] and "已经生成完整PA4流程" not in result["answer"]
    assert returned["source"] == "bundled" and returned["knowledgeVersion"]
    assert any(t["function"]["name"] == "lookup_pin" for t in TOOLS)


def test_missing_gpio_reset_reports_actual_blocker_without_false_delivery(tmp_path):
    request = {"name": "PA4_MCO", "chip": "py32f420", "directives": [
        {"kind": "field_value", "peri": "RCC", "reg": "CFGR1", "field": "MCO2SEL", "value": 2},
        {"kind": "field_value", "peri": "RCC", "reg": "CFGR1", "field": "MCO2PRE", "value": 14},
        {"kind": "clk_enable", "periph": "GPIOA"},
        {"kind": "pin_config", "pin": "PA4", "func": "MCO2"}]}
    result, client = run(tmp_path, [tool("prepare_swd", {"request": request})])
    assert not result["candidates"]
    assert result["status"] == "needs_input"
    question, = result['knowledgeQuestions']
    assert question['register'] == 'AFRL' and 'AFSEL0' in question['fields']
    assert '未生成' in result['answer']
    assert len(client.messages) == 1  # A frozen knowledge defect cannot be repaired by more searches.


def test_pin_query_returns_executable_complete_gpio_directive(tmp_path):
    from gui.assistant_swd import prepare_candidate
    from swd_authoring import EncodingDB
    from tests.test_assistant_reset_domain import SUPPLEMENT
    _, client = run(tmp_path, [tool('lookup_pin', {'pin': 'PA4'})])
    returned = json.loads(client.messages[1][-1]['content'])
    recipe = returned['pinConfig']
    directive = next(d for d in recipe['directives'] if d['func'] == 'MCO2')
    assert directive['mode'] == 'GPIO_MODE_AF_PP'
    assert directive['speed'] == 'GPIO_SPEED_FREQ_VERY_HIGH'
    assert directive['pull'] == 'GPIO_NOPULL'
    result = prepare_candidate({'name':'PinContract','chip':'py32f420','directives':[
        {'kind':'clk_enable','periph':'GPIOA'}, directive]}, product_profile_id='PCD009',
        platform='chroma',initial_state='reset',db=EncodingDB('py32f420',reset_supplements=[SUPPLEMENT]))
    words = {r['addr']:r['data'] for r in result['rows']}
    assert words == {'0x40021074':'0x00000001','0x40024020':'0x00000000',
                     '0x40024004':'0x00000000','0x40024008':'0x0C000300',
                     '0x4002400C':'0x64000000','0x40024000':'0xABFFFEFF'}
