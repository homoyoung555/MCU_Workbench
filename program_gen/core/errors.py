# 全局异常处理：出错时反推 Excel 位置（平台无关）。
import re
import traceback


def excel_error_backtrack(exc_type, exc_value, exc_traceback):
    """
    全局异常处理器，当程序报错时自动反推Excel位置
    
    使用方法：
        sys.excepthook = excel_error_backtrack
    
    当程序出错时，会遍历整个调用链，显示所有Excel访问位置
    """
    print("\n" + "="*80)
    print("【错误分析】自动反推Excel位置")
    print("="*80)
    
    tb = exc_traceback
    error_locations = []
    
    while tb is not None:
        frame = tb.tb_frame
        filename = frame.f_code.co_filename
        lineno = tb.tb_lineno
        
        if "pattern.py" in filename:
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                start_line = max(0, lineno - 2)
                end_line = min(len(lines), lineno + 1)
                context_lines = lines[start_line:end_line]
                
                for line_num, line in enumerate(context_lines, start=start_line+1):
                    df_pattern = r'list\((ADDR_MAP|FLOW|VERSION|PATTERN|PIN_DEC_128|NM_PATTERN|FLASH_EPR|KP_RELAY)\[("[^"]*")\]\)'
                    df_match = re.search(df_pattern, line)
                    
                    if df_match:
                        df_name = df_match.group(1)
                        matched_text = df_match.group(0)
                        
                        df_start = line.find(matched_text)
                        if df_start >= 0:
                            search_str = line[df_start:]
                            col_pattern = r'"([^"]*)"'
                            col_matches = re.findall(col_pattern, search_str)
                            column = col_matches[0] if col_matches else "未知列"
                            
                            bracket_start = search_str.find('])[')
                            if bracket_start >= 0:
                                bracket_content = search_str[bracket_start+2:]
                                bracket_end = len(bracket_content) - 1
                                depth = 1
                                for i, c in enumerate(bracket_content):
                                    if c == '[':
                                        depth += 1
                                    elif c == ']':
                                        depth -= 1
                                        if depth == 0:
                                            bracket_end = i
                                            break
                                index_expr = bracket_content[:bracket_end]
                            else:
                                index_expr = ""
                        else:
                            column = "未知列"
                            index_expr = ""
                        
                        index_value = "?"
                        
                        if index_expr:
                            final_index = None
                            
                            try:
                                index_result = eval(index_expr, {"__builtins__": {}}, frame.f_locals)
                                if isinstance(index_result, (int, float)):
                                    final_index = int(index_result)
                            except:
                                pass
                            
                            if final_index is None:
                                math_expr = re.match(r'\[?([^\[\]]+(?:\[[^\]]+\])?(?:[*+\-/][^\[\]]+(?:\[[^\]]+\])?)*)\]?\.?', index_expr)
                                if math_expr:
                                    try:
                                        math_result = eval(math_expr.group(1), {"__builtins__": {}}, frame.f_locals)
                                        if isinstance(math_result, (int, float)):
                                            final_index = int(math_result)
                                    except:
                                        pass
                            
                            if final_index is not None:
                                excel_row = final_index + 2
                                index_value = f"= {final_index} → Excel第{excel_row}行"
                            else:
                                var_pattern = r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b'
                                potential_vars = re.findall(var_pattern, index_expr)
                                keywords = {'and', 'or', 'not', 'in', 'is', 'if', 'else', 'for', 'while', 'True', 'False', 'None'}
                                index_vars = [v for v in potential_vars if v not in keywords]
                                
                                found_vars = []
                                for var in index_vars[:5]:
                                    if var in frame.f_locals:
                                        val = frame.f_locals.get(var, '?')
                                        val_str = str(val)
                                        if len(val_str) > 30:
                                            val_str = val_str[:30] + "..."
                                        found_vars.append(f"{var}={val_str}")
                                
                                if found_vars:
                                    index_value = f"[{', '.join(found_vars)}]"
                                else:
                                    index_value = ""
                        
                        df_mapping = {
                            'ADDR_MAP': 'ADDR_MAP',
                            'FLOW': 'FLOW', 
                            'VERSION': 'VERSION',
                            'PATTERN': 'PATTERN',
                            'PIN_DEC_128': 'PIN_DEC_128',
                            'NM_PATTERN': 'NM_PATTERN',
                            'FLASH_EPR': 'FLASH_EPR',
                            'KP_RELAY': 'KP_RELAY'
                        }
                        sheet_name = df_mapping.get(df_name, df_name)
                        
                        error_locations.append({
                            'filename': filename,
                            'line': line_num,
                            'sheet': sheet_name,
                            'df': df_name,
                            'column': column,
                            'index_value': index_value,
                            'code': line.strip()
                        })
                        
            except Exception as e:
                pass
        
        tb = tb.tb_next
    
    if error_locations:
        print("\n可能涉及的Excel位置：")
        print("-" * 80)
        for loc in error_locations:
            print(f"\n  📍 {loc['filename']} 第{loc['line']}行")
            print(f"     Sheet: {loc['sheet']}, 列名: {loc['column']}")
            print(f"     索引: {loc['index_value']}")
    else:
        print("\n⚠️  未能在调用链中找到Excel访问位置")
    
    print("\n" + "="*80)
    print("【原始错误信息】")
    print("="*80)
    traceback.print_exception(exc_type, exc_value, exc_traceback)
    
    print("="*80)
    print("请根据上述【错误分析】定位Excel中的具体位置")
    print("="*80 + "\n")
