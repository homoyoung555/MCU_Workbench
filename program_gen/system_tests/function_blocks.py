"""Pure dual-platform renderers for mandatory system read typed kinds."""

from __future__ import annotations


def render_system_read_body(spec, target) -> str:
    platform = target.platform.casefold()
    if spec.typed_kind == "SYSTEM_OTP_READ":
        return _chroma_otp(spec) if platform == "chroma" else _s100_otp(spec)
    if spec.typed_kind == "SYSTEM_NM_DATA_READ":
        return _chroma_nm(spec) if platform == "chroma" else _s100_nm(spec)
    raise ValueError(f"SYS.READ.KIND.UNSUPPORTED: {spec.typed_kind!r}")


def _chroma_otp(spec) -> str:
    byte_count = spec.page_bytes
    gs = max(1, spec.read_bit // 32)
    addresses = "{" + ",".join(f"0x{value:02X}" for value in spec.ra_addresses) + "}"
    return (
        "OTP_Read()\r\n{\r\n"
        "  // System test: read OTP contents.\r\n"
        "  TEST_NUM=999900;\r\n  TEST_NO(TEST_NUM);DATALOG_MSG=\"OTP_Read\";\r\n\r\n"
        f"  int byte_count={byte_count};\r\n"
        f"  int otp_read_bit[{byte_count * 8}];//{byte_count} byte\r\n"
        f"  int otp_data[1][{byte_count}];//page,byte\r\n"
        f"  int temp=0;\r\n  int addr_arry[{len(spec.ra_addresses)}]={addresses};\r\n\r\n"
        "  POWER_ON(VCC_TYP);\r\n"
        "  TEST_NUM++;\r\n  TEST_NO(TEST_NUM); DATALOG_MSG=\"enter_fbist_mode\";\r\n"
        "  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode);\r\n\r\n"
        f"  SET_CAPTURE_MEM_MODE({spec.swd_pin}, PEL_K, ON, 64K);\r\n\r\n"
        "  SOCKET_INC(FRZ_OFF)\r\n  {\r\n"
        "    for(int cyc=0;cyc<sizeof(addr_arry)/sizeof(addr_arry[0]);cyc++)\r\n    {\r\n"
        "      temp=addr_arry[cyc];\r\n"
        "      for(J=0;J<=7;J++){BIT[J]=temp%2;temp=temp/2;}\r\n"
        "      for(J=7;J>=0;J--)\r\n      {\r\n"
        "        if(BIT[J]==0)\r\n        {\r\n"
        f"          WRITE_PAT_MEM(SOCKET,{spec.swd_pin},otp_read:addr+7-J,,\"0\");\r\n"
        "        }\r\n        else\r\n        {\r\n"
        f"          WRITE_PAT_MEM(SOCKET,{spec.swd_pin},otp_read:addr+7-J,,\"1\");\r\n"
        "        }\r\n"
        "      }\r\n"
        "      TEST_NUM++;\r\n      TEST_NO(TEST_NUM); DATALOG_MSG=\"otp_read\";\r\n"
        "      JUDGE_PAT(otp_read,__otp_read);\r\n\r\n"
        "      for(J=0;J<byte_count*8;J++) otp_read_bit[J]=8;\r\n"
        f"      READ_CAPTURE_MEM_BLOCK(SOCKET,{spec.swd_pin},0,{byte_count * 8 - 1},otp_read_bit);\r\n"
        "      for(I=0;I<1;I++)\r\n      {\r\n"
        "        for(J=0;J<byte_count;J++)\r\n        {\r\n"
        "          otp_data[I][J]=0;\r\n"
        "          for(K=0;K<8;K++)\r\n          {\r\n"
        "            if(otp_read_bit[byte_count*8*I+8*J+K]!=8)\r\n"
        "            {\r\n"
        "              otp_data[I][J]+=otp_read_bit[byte_count*8*I+8*J+K]<<(7-K);\r\n"
        "            }\r\n          }\r\n"
        "        }\r\n      }\r\n"
        "      for(I=0;I<1;I++)\r\n      {\r\n"
        "        printf(\"- SM - Bit31  -->   Bit0\\n\");\r\n"
        "        for(J=0;J<byte_count/4;J++)\r\n        {\r\n"
        f"          int index=(J/{gs})*{gs}+({gs}-1-(J%{gs}));\r\n"
        "          printf(\"0x%04X:\",addr_arry[cyc]*byte_count+J*4);\r\n"
        "          for(K=0;K<4;K++)\r\n          {\r\n"
        "            if(otp_data[I][4*index+K]<=0xF&&otp_data[I][4*index+K]>=0x0) "
        "printf(\"  0%X\",otp_data[I][4*index+K]);\r\n"
        "            else printf(\"  %2X\",otp_data[I][4*index+K]);\r\n"
        "          }\r\n          printf(\"\\n\");\r\n        }\r\n"
        "        printf(\"\\n\");\r\n      }\r\n      fflush(stdout);\r\n"
        "    }\r\n  }\r\n\r\n"
        f"  SET_CAPTURE_MEM_MODE({spec.swd_pin}, PEL_K, OFF, 64K);\r\n\r\n"
        "  TEST_NUM++;\r\n  TEST_NO(TEST_NUM); DATALOG_MSG=\"exit_fbist_mode\";\r\n"
        "  JUDGE_PAT(exit_fbist_mode,__exit_fbist_mode);\r\n"
        "  POWER_OFF();\r\n}\r\n\r\n"
    )


def _chroma_nm(spec) -> str:
    ecm_x = 8
    print_rows = spec.page_bytes // 16
    return (
        "NM_Data_Read()\r\n{\r\n"
        "  // System test: dump nonvolatile memory data.\r\n"
        "  TEST_NUM=999800;\r\n  TEST_NO(TEST_NUM);DATALOG_MSG=\"NM_Data_Read\";\r\n\r\n"
        f"  int page_count={spec.page_count};\r\n  int page_byte={spec.page_bytes};\r\n"
        "  CUSTOM_3DIM_BOOL temp_nm_data;\r\n"
        f"  int main_data[{spec.page_bytes}];//one page bytes\r\n"
        "  FILE *fp1;\r\n  char filepath[255];\r\n\r\n"
        "  POWER_ON(VCC_TYP);\r\n"
        "  TEST_NUM++;\r\n  TEST_NO(TEST_NUM); DATALOG_MSG=\"enter_fbist_mode\";\r\n"
        "  JUDGE_PAT(enter_fbist_mode,__enter_fbist_mode);\r\n\r\n"
        f"  SET_ECM_MODE({spec.swd_pin},PEL_K,ON,X{ecm_x});\r\n\r\n"
        "  SOCKET_INC(FRZ_OFF)\r\n  {\r\n"
        "    sprintf(filepath,\".\\\\..\\\\S%d_main.txt\",SOCKET);\r\n"
        "    fp1=fopen(filepath,\"w\");\r\n"
        "    TEST_NUM++;\r\n    TEST_NO(TEST_NUM); DATALOG_MSG=\"nm_read\";\r\n"
        "    JUDGE_PAT(nm_read,__nm_read);\r\n"
        f"    READ_ECM_BLOCK({spec.swd_pin},0,page_count*page_byte*8-1,temp_nm_data);\r\n"
        "    fprintf(fp1,\"=============================== Site %d ===============================\\n\",SOCKET);\r\n"
        "    fprintf(fp1,\"  -user-    0x0 0x1 0x2 0x3 0x4 0x5 0x6 0x7 0x8 0x9 0xA 0xB 0xC 0xD 0xE 0xF\\n\");\r\n"
        "    for(I=0;I<page_count;I++)\r\n    {\r\n"
        "      for(J=0;J<page_byte;J++)\r\n      {\r\n        main_data[J]=0;\r\n"
        "        for(K=0;K<8;K++)\r\n        {\r\n"
        "          main_data[J]+=(temp_nm_data[SOCKET][0][page_byte*8*I+8*J+K]<<(7-K));\r\n"
        "        }\r\n"
        "      }\r\n"
        f"      for(J=0;J<{print_rows};J++)\r\n      {{\r\n"
        "        fprintf(fp1,\"0x080%03X%02X:\",I,J*16);\r\n"
        "        for(K=0;K<16;K++)\r\n        {\r\n"
        f"          int index=(K/{ecm_x})*{ecm_x}+({ecm_x}-1-(K%{ecm_x}));\r\n"
        "          fprintf(fp1,\"  %02X\",main_data[16*J+index]);\r\n"
        "        }\r\n        fprintf(fp1,\"\\n\");\r\n      }\r\n    }\r\n"
        "    fclose(fp1);\r\n  }\r\n  fflush(stdout);\r\n"
        f"  SET_ECM_MODE({spec.swd_pin},PEL_K,OFF,X{ecm_x});\r\n"
        "  TEST_NUM++;\r\n  TEST_NO(TEST_NUM); DATALOG_MSG=\"exit_fbist_mode\";\r\n"
        "  JUDGE_PAT(exit_fbist_mode,__exit_fbist_mode);\r\n"
        "  POWER_OFF();\r\n}\r\n\r\n"
    )


def _s100_otp(spec) -> str:
    gs = max(1, spec.read_bit // 32)
    addresses = "{" + ",".join(f"0x{value:02X}" for value in spec.ra_addresses) + "}"
    return (
        "@@PLAN OTP_Read\r\n"
        "  // System test: read OTP contents.\r\n"
        "  SITE_SEQUENCE      = OFF;\r\n  DISABLE_BY_MARK_NO = NULL;\r\n"
        "  S_SETUP_FILE       = c:\\set.dat;\r\n  REMARK             = OTP_Read;\r\n\r\n"
        f"  int r=0;\r\n  int addr;\r\n  int cyc;\r\n  int byte_count={spec.page_bytes};\r\n"
        f"  int addr_arry[{len(spec.ra_addresses)}]={addresses};\r\n  char buffer[2000];\r\n\r\n"
        "  CALL_MACRO POWER_ON(_C_VCC_TYP);\r\n"
        "  RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);\r\n"
        "  for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\r\n  {\r\n"
        "    if(Sys_ActiveSite[T_SOCKET]==0)continue;\r\n"
        f"    for(cyc=0;cyc<{len(spec.ra_addresses)};cyc++)\r\n    {{\r\n"
        "      GB[0+T_SOCKET*64]=addr_arry[cyc];\r\n      addr=GB[0+T_SOCKET*64];\r\n"
        "      C_COMPARE(GB1,UP_LIMIT=2048,DOWN_LIMIT=0.0,LOG_ALIAS=ADD,HEX);\r\n"
        f"      LOGIC_WRITE_PATTERN_MEMORY(otp_read:START2,otp_read:END2,{spec.swd_pin},GB1,BIT_COUNT=8,SERIAL,FAST_MODE,VERIFY_DATA);\r\n"
        "      LOGIC_SET_AC_DATALOG(otp_read:START1,otp_read:END,LOG_ENABLE_ALL,AC_IGNORE_FAIL);\r\n"
        "      RUN_PATTERN(otp_read:START,otp_read:END,1,TS_5MHZ);\r\n"
        f"      LOGIC_READ_LOG(otp_log,{spec.swd_pin},{spec.page_bytes * 8},1,BIN,TRIG_PINNAME=TRIGPIN);\r\n"
        "      for(J=0;J<byte_count;J++)\r\n      {\r\n        main_data[T_SOCKET][J]=0;\r\n"
        "        for(K=0;K<8;K++)\r\n        {\r\n"
        "          main_data[T_SOCKET][J]+=((int)Sys_SW_BUFFER_DATA[T_SOCKET][8*J+K]<<(7-K));\r\n"
        "        }\r\n"
        "      }\r\n"
        "      for(J=0;J<byte_count/4;J++)\r\n      {\r\n"
        f"        int index=(J/{gs})*{gs}+({gs}-1-(J%{gs}));\r\n"
        "        sprintf(buffer,\"0x%02X%02X: %02X %02X %02X %02X\",addr,J*4,"
        "main_data[T_SOCKET][4*index+0],main_data[T_SOCKET][4*index+1],"
        "main_data[T_SOCKET][4*index+2],main_data[T_SOCKET][4*index+3]);\r\n"
        "        WRITELN(buffer);\r\n      }\r\n    }\r\n  }\r\n"
        "  RUN_PATTERN(exit_fbist_mode:START,exit_fbist_mode:END,1,TS_5MHZ);\r\n"
        "  CALL_MACRO POWER_OFF();\r\n\r\n"
        "  CONDITION\r\n    IF_FAIL\r\n    REJECT_BIN=16;\r\n@@END_PLAN\r\n\r\n"
    )


def _s100_nm(spec) -> str:
    gs = max(1, spec.read_bit // 32)
    chunks = [
        "@@PLAN NM_Data_Read\r\n",
        "  // System test: dump nonvolatile memory data.\r\n",
        "  SITE_SEQUENCE      = OFF;\r\n  DISABLE_BY_MARK_NO = NULL;\r\n",
        "  S_SETUP_FILE       = c:\\set.dat;\r\n  REMARK             = NM_Data_Read;\r\n\r\n",
        f"  int r=0;\r\n  int page_byte={spec.page_bytes};\r\n",
        "  FILE *fp1;\r\n  char filepath[255];\r\n\r\n",
        "  CALL_MACRO POWER_ON(_C_VCC_TYP);\r\n",
        "  RUN_PATTERN(enter_fbist_mode:START,enter_fbist_mode:END,1,TS_5MHZ);\r\n",
        "  for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)\r\n  {\r\n",
        "    if(Sys_ActiveSite[T_SOCKET]==0)continue;\r\n",
        "    sprintf(filepath,\".\\\\S%d_main.txt\",T_SOCKET);\r\n    fp1=fopen(filepath,\"w\");\r\n",
    ]
    for bank in range(spec.bank_count):
        pattern = f"fbist_capture_nm_bank{bank}"
        base = f"({bank * spec.pages_per_bank}+r)*page_byte"
        chunks.extend((
            f"    r=0;\r\n    LOGIC_SET_AC_DATALOG({pattern}:START,{pattern}:END1,LOG_ENABLE_ALL,AC_IGNORE_FAIL);\r\n",
            f"    RUN_PATTERN({pattern}:START,{pattern}:END1,1,TS_5MHZ);\r\n",
            f"    LOGIC_READ_LOG(nm_log,{spec.swd_pin},{spec.page_bytes * 8},1,BIN,TRIG_PINNAME=TRIGPIN);\r\n",
            _s100_nm_page_dump(spec, gs, base),
            f"    for(r=1;r<{spec.pages_per_bank};r++)\r\n    {{\r\n",
            f"      LOGIC_SET_AC_DATALOG({pattern}:START2,{pattern}:END2,LOG_ENABLE_ALL,AC_IGNORE_FAIL);\r\n",
            f"      RUN_PATTERN({pattern}:START2,{pattern}:END2,1,TS_5MHZ);\r\n",
            f"      LOGIC_READ_LOG(nm_log,{spec.swd_pin},{spec.page_bytes * 8},1,BIN,TRIG_PINNAME=TRIGPIN);\r\n",
            _s100_nm_page_dump(spec, gs, base, indent="      "),
            "    }\r\n",
        ))
    chunks.extend((
        "    fclose(fp1);\r\n  }\r\n",
        "  RUN_PATTERN(exit_fbist_mode:START,exit_fbist_mode:END,1,TS_5MHZ);\r\n",
        "  CALL_MACRO POWER_OFF();\r\n\r\n",
        "  CONDITION\r\n    IF_FAIL\r\n    REJECT_BIN=16;\r\n@@END_PLAN\r\n\r\n",
    ))
    return "".join(chunks)


def _s100_nm_page_dump(spec, gs: int, base: str, indent: str = "    ") -> str:
    rows = spec.page_bytes // 16
    i = indent
    return (
        f"{i}for(J=0;J<page_byte;J++)\r\n{i}{{\r\n{i}  main_data[T_SOCKET][J]=0;\r\n"
        f"{i}  for(K=0;K<8;K++)\r\n{i}  {{\r\n"
        f"{i}    main_data[T_SOCKET][J]+=((int)Sys_SW_BUFFER_DATA[T_SOCKET][8*J+K]<<(7-K));\r\n{i}  }}\r\n{i}}}\r\n"
        f"{i}for(J=0;J<{rows};J++)\r\n{i}{{\r\n{i}  fprintf(fp1,\"0x080%05X:\",{base}+J*16);\r\n"
        f"{i}  for(K=0;K<16;K++)\r\n{i}  {{\r\n"
        f"{i}    int index=(K/{gs})*{gs}+({gs}-1-(K%{gs}));\r\n"
        f"{i}    fprintf(fp1,\"  %02X\",main_data[T_SOCKET][16*J+index]);\r\n"
        f"{i}  }}\r\n{i}  fprintf(fp1,\"\\n\");\r\n{i}}}\r\n"
    )


__all__ = ["render_system_read_body"]
