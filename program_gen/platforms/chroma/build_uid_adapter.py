"""Chroma syntax for compiler-owned BUILDUID values and startup policy."""

from program_gen.recipe_module_registry import RecipeModuleEmission


def adapt_build_uid(plan):
    policy = plan.policy_for("chroma")
    if policy.crc_scope != "PER_SITE":
        raise ValueError("BUILDUID.CHROMA_CRC_SCOPE")
    lower, upper = policy.coordinate_limits
    lines = ["  int day,month,year;", "  time_t secnow;", "  time(&secnow);",
             "  struct tm *tmptr=localtime(&secnow);",
             "  day=tmptr->tm_mday; month=tmptr->tm_mon+1; year=tmptr->tm_year-100;"]
    if policy.refresh_coordinates:
        lines.append("  READ_PROBER_XY(X_CO,Y_CO);")
    lines.extend(("  SOCKET_INC(FRZ_OFF)", "  {",
                  f'    JUDGE_VARIABLE(SOCKET,X_CO[SOCKET],{lower},{upper},"X_CO");',
                  f'    JUDGE_VARIABLE(SOCKET,Y_CO[SOCKET],{lower},{upper},"Y_CO");',
                  "  }", "  SOCKET_INC(FRZ_OFF)", "  {"))
    lines.append("    unsigned char ucPtr[14];")
    lines.extend(f"    ucPtr[{index}]={expression};" for index, expression in enumerate(policy.crc_inputs))
    lines.append("    unsigned char CRC8=GetCRC8(ucPtr,0x0E);")
    lines.extend(f"    {symbol}[SOCKET]={expression};" for symbol, expression in policy.word_expressions)
    lines.append("  }")
    return RecipeModuleEmission(statements=tuple(lines))


def render_build_uid_support(plan):
    policy = plan.policy_for("chroma")
    globals_text = "\n".join(
        [f"int {name}={value};" for name, value in plan.constants]
        + [f"{word.value_type} {word.symbol}[MAX_SITE];" for word in plan.words]
        + ["int LOAD_ID_FLAG;"]
    ) + "\n"
    helpers = (
        "unsigned char const CRC8_TAB[256]={\n  "
        + ",\n  ".join(",".join(f"0x{value:02X}" for value in plan.crc_table[i:i+16]) for i in range(0,256,16)) + "\n};\n"
        +
        "unsigned char GetCRC8(unsigned char *ucPtr,unsigned char ucLen)\n"
        "{\n  unsigned char crc=0;\n  while(ucLen--)\n  {\n"
        "    crc=CRC8_TAB[crc^(*ucPtr++)];\n"
        "  }\n  return (unsigned char)(~crc);\n}\n"
    )
    startup = "  LOAD_ID_FLAG=1;\n" if policy.manual_wafer_input else ""
    test_start = ""
    if policy.manual_wafer_input:
        test_start = (
            "  if(LOAD_ID_FLAG==1)\n  {\n"
            "    READ_WAFER_ID(WAFERID,LOT_ID);\n"
            '    printf("WAFER ID = %s , LOT ID = %s\\n",WAFERID,LOT_ID);\n'
            "    if(strlen(WAFERID)<10)\n    {\n"
            '      INPUT_BOX("Not found WAFER ID!\\n1. Enter ID and Press OK.\\n+2. Press Cancel ande ID will be all 0xFF.\\n)","%s %s",WAFERID,LOT_ID);\n'
            '      printf("Manual INPUT WAFER ID = %s , LOT ID = %s\\n",WAFERID,LOT_ID);\n'
            "    }\n"
            "    if(strlen(WAFERID)>10) WAFER_SLOT=((int)WAFERID[8]-48)*10+((int)WAFERID[9]-48);\n"
            "    else\n    {\n      WAFER_SLOT=0xFF;\n"
            "      for(I=0;I<7;I++) LOT_ID[I]=0xFF;\n      ABORT_TEST_PLN();\n    }\n"
            "    if((WAFER_SLOT<1)||(WAFER_SLOT>25)) ABORT_TEST_PLN();\n"
            '    printf("Slot No = %d\\n",WAFER_SLOT);\n'
            "    fflush(stdout);\n    LOAD_ID_FLAG=0;\n  }\n"
        )
    return globals_text, helpers, startup, test_start
