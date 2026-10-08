"""Recipe editing projection; parsing and defaults stay owned by flow_recipe."""
from flow_recipe import (
    FlowCompileError, parse_recipe, default_recipe, _split_recipe_line, _CALL_RE,
    _MODULE_ARGUMENTS, _MODULE_TIME_PARAMETERS, _MODULE_TEXT_PARAMETERS,
)


# Descriptions explain business operations; accepted parameter sets come from the parser.
DESCRIPTIONS = {
    'ENTER': '进入当前测试项的测试配置，绑定相应 Pattern；可指定动态位串、角色和进入后的等待时间。',
    'TRIM': '执行当前测试项的校准搜索并得到最终 DAC；搜索方式、点集和目标来自 FLOW 及关联配置。',
    'JUDGE': '执行当前流程对应的测量或结果判定；引脚、目标、上下限和单位来自 FLOW。PF 控制是否产生通过/失败判定。',
    'DEPEND': '引用其他校准项的结果作为测试条件；只声明结果依赖，不代表已将结果持久写入 OTP/UID。',
    'DAC_WRITE': '向当前项绑定的动态 DAC 字段写值；省略位串时按当前流程的结果来源处理。SHMOO=STEP 使用 FLOW step 点集。',
    'DAC_ADJ': '根据条件或固定偏移调整校准后的 DAC，并按当前流程回写/复测；必须在校准结果已产生后使用。',
    'RUN': '运行指定名称的 Pattern；Pattern 必须实际存在并能满足目标平台资源要求。',
    'EXPORT': '把当前结果导出为测试程序内的变量，供后续模块使用；本模块不直接写入芯片。',
    'READID': '读取当前 ID 项定义的芯片标识，具体目标由 item/流程合同确定。',
    'CHECKID': '检查当前 ID 项定义的标识与门禁条件；需满足对应流程的状态和依赖要求。',
    'BUILDUID': '构造 UID 所需的数据内容，字段来源由当前产品与流程配置确定。',
    'COMMIT': '组装待写入的字段值；可显式指定字段赋值。实际编程由后续编程模块完成。',
    'BUILDMAP': '根据 ADDR_MAP 与当前 CP 的结果构建寄存器/页映像，供后续 Flash 操作使用。',
    'LOADMAP': '将已准备的页映像装载到对应 Pattern 数据区；可指定 UID 页范围。',
    'PGMOTP': '执行当前流程允许的 OTP/UID 编程，消费已准备的数据与编程条件。',
    'READOTPMAP': '读取 OTP/UID 页数据并恢复流程需要的寄存器或 DAC 字段。',
    'CHECKOTP': '对已读取的 OTP/UID 数据进行当前流程规定的检查。',
    'SETVPOSP': '应用当前已产生的 PUMP 校准结果，准备后续测试或 Flash 擦写条件。',
    'NMLOOP': '执行 Flash 窗口流程中的 NM 操作序列；动作与资源依据当前流程计划闭合。',
    'NM_TEST': '执行正常存储器测试或 repair 测试；不指定参数时由当前流程决定模式。',
    'VT_TEST': '执行阈值电压相关测试，可选择 NM 或指定 OTP 页面。VT 是此模块的语法别名。',
    'MARGIN_TEST': '执行存储器裕量测试，可选择 NM 或指定 OTP 页面。MARGIN 是此模块的语法别名。',
    'RUN_SEQUENCE': '按 FLOW step 中的有序动作执行进入、触发、等待或 Force 等操作；结果判定/Capture 由后续模块显式连接。',
    'SRAM_CAPTURE': '按地址、数量、位宽和步长抓取无符号小端 SRAM 结果。Chroma 普通 KEIL：首行 RUN_SEQUENCE-SRAM_CAPTURE(...)-JUDGE，后续同一 item 连续行各填 JUDGE，依次判定每个值；数量必须匹配，过程中不重新触发或复位。UNIT=/、target=/，上下限填绝对数值。',
    'SWD_CAPTURE': '执行当前原生流程定义的 SWD 数据采集；采集配置来自该流程及关联工作表。',
    'ADC_JUDGE': '按 ADC 工作表中的通道、激励和限值判断已采集的 ADC 数据。',
    'DC_TEST': '执行当前直流测试流程，测量条件和限值来自 FLOW。',
    'VIH_VIL_TEST': '执行输入高/低阈值测试，使用对应流程的步进、引脚和判定配置。',
    'PVD_TEST': '执行 PVD 上升/下降阈值测试；测试案例、期望状态与电压范围来自 PVD 表。',
    'FREQ_TEST': '执行频率测试；时钟源、倍频、分频、步进和限值来自 FREQ 表。',
    'OPA_TEST': '执行运放测试；模式、输入激励、目标和限值来自 OPA 表。',
    'DAC_TEST': '执行 DAC 测试；模式、码值、上下限和步进来自 DAC 表。',
}
ARGUMENT_HELP = {
    'ENTER': '可选位置参数为二进制位串，保留前导零，如 0010。',
    'DAC_WRITE': '可选位置参数为二进制位串，如 0010。',
    'DEPEND': '位置参数为依赖项标识符，如 Vref0p8_ABS；实际来源须被当前流程允许。',
    'RUN': '必填位置参数：Pattern 名称，英文字母开头，后续可用字母、数字、下划线。',
    'DAC_ADJ': '调整式示例：+1、-1、<0.8:+1、>=0.8:-1；阈值和偏移需符合当前校准逻辑。',
    'COMMIT': '字段=值，多项用逗号分隔；值支持十进制、0x 十六进制、0b 二进制、STEP 或变量标识符，不允许重复字段。',
    'SRAM_CAPTURE': 'base,countxwidth[@stride]：base 为十进制/十六进制地址；count>0，width 为1..32位；stride 为字节步长，省略时固定为4。连续16位结果请显式写@2。最后一个值不得越过0xFFFF。普通 KEIL 的采集引脚取当前 CP 的 VERSION SWD PIN，后续 JUDGE 行 step 留空或填 /。',
    'NM_TEST': '可选位置参数 normal 或 repair。',
    'VT_TEST': '可选位置参数 NM 或 OTP-页面名，例如 OTP-trim0。',
    'MARGIN_TEST': '可选位置参数 NM 或 OTP-页面名，例如 OTP-trim0。',
    **{name: '可不填位置参数；第一版显式位置参数仅支持 UID，其他页面由当前流程合同决定。'
       for name in ('READOTPMAP', 'LOADMAP', 'CHECKOTP', 'PGMOTP')},
}
EXAMPLES = {'ENTER': 'ENTER(ROLE=VERIFY,WAIT=1MS)', 'TRIM': 'TRIM(FWAIT=1MS,SWAIT=10US)',
            'JUDGE': 'JUDGE(PF=YES)', 'RUN': 'RUN(enter_fbist_mode)', 'DEPEND': 'DEPEND(Vref0p8_ABS)',
            'DAC_WRITE': 'DAC_WRITE(0010)', 'DAC_ADJ': 'DAC_ADJ(<0.8:+1)',
            'EXPORT': 'EXPORT(FORMAT=RAW)', 'COMMIT': 'COMMIT(trim=0b0010)',
            'SRAM_CAPTURE': 'SRAM_CAPTURE(0x100,2x16@4)', 'NM_TEST': 'NM_TEST(normal)',
            'VT_TEST': 'VT_TEST(OTP-trim0)', 'MARGIN_TEST': 'MARGIN_TEST(NM)'}


def module_manual():
    modules = []
    for name, has_argument in _MODULE_ARGUMENTS.items():
        reserved = name not in DESCRIPTIONS
        parameters = [ARGUMENT_HELP.get(name, '不接受位置参数。' if not has_argument else '语法接受二进制位串；当前无可用业务说明。')]
        for key in sorted(_MODULE_TIME_PARAMETERS.get(name, ())):
            meaning = {'WAIT': '进入配置后等待', 'FWAIT': 'Force 后等待', 'SWAIT': '测量前等待'}[key]
            parameters.append(f'{key}：{meaning}，非负整数 + US/MS，例如 {key}=1MS。')
        for key, values in _MODULE_TEXT_PARAMETERS.get(name, {}).items():
            parameters.append(f'{key}：' + ' / '.join(sorted(values)) + '。')
        if name == 'EXPORT': parameters.append('RAW 保留原始结果；BCD16_MV 为毫伏BCD编码；ADC12_3V3 为3.3V参考的12位ADC编码。')
        if name == 'ENTER': parameters.append('ROLE 选择 TRIM/VERIFY 配置角色；SHMOO=STEP 按 FLOW step 扫描。')
        if name in ('ENTER', 'TRIM'):
            parameters.append('PATTERN=完整名称：普通 TRIM 当前行的显式 Pattern；建议通过关联区“选择 Pattern 用途”填写。TRIM 的选择同时用于搜索、DAC调整和最终判定。')
        modules.append({'name': name, 'description': DESCRIPTIONS.get(name, '语法保留名称；当前未发现对应的原生业务执行实现，不建议用于新增流程。'),
                        'parameters': parameters, 'example': '' if reserved else EXAMPLES.get(name, name),
                        'reserved': reserved})
    return modules


def inspect_recipe(payload):
    values = {key: payload.get(key, '') for key in ('text', 'item', 'type', 'mode')}
    if any(not isinstance(value, str) or len(value) > 32767 for value in values.values()):
        raise ValueError('Recipe 及上下文必须是最多32767字符的文本')
    raw = values['text']
    result = {'text': raw, 'steps': [], 'source': 'explicit' if raw.strip() else 'blank',
              'error': '', 'issues': [], 'warnings': [], 'defaultText': '', 'manual': module_manual()}
    try:
        if values['mode'].strip().casefold() == 'hex':
            result['source'] = 'intrinsic'
            if raw.strip():
                result['error'] = 'HEX 下载行的 Recipe 必须留空；下载阶段由 mode=hex 隐式确定。'
                result['issues'] = [{'index': None, 'message': result['error']}]
            return result
        text = raw
        if not raw.strip():
            text = default_recipe(values['item'], values['type'], values['mode']) or ''
            result['defaultText'] = text
            if text: result['source'] = 'default'
        if not text: return result
        tokens = []
        for line in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
            if not line.strip(): continue
            tokens.extend(_split_recipe_line(line))
        for index, token in enumerate(tokens):
            try:
                calls = parse_recipe(token)
                if any(m['reserved'] and m['name'] == calls[0].name for m in result['manual']):
                    result['warnings'].append({'index': index, 'message': '保留模块：当前未发现原生业务执行实现，不建议新增；语法检查允许保留。'})
            except FlowCompileError as error:
                result['issues'].append({'index': index, 'message': str(error)})
        parse_recipe(text)  # Whole Recipe remains the production grammar's responsibility.
        for token in tokens:
            match = _CALL_RE.fullmatch(token.strip())
            result['steps'].append({'module': match.group(1), 'arguments': match.group(2) or ''})
    except FlowCompileError as error:
        result['steps'] = []
        result['error'] = str(error)
        if not result['issues']:
            result['issues'] = [{'index': None, 'message': str(error)}]
    return result
