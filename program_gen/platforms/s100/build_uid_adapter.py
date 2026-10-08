"""S100 BUILDUID syntax retaining the current generator's explicit policies."""

from program_gen.recipe_module_registry import RecipeModuleEmission


def adapt_build_uid(plan):
    policy = plan.policy_for("s100")
    if policy.crc_scope != "LAST_SITE_BROADCAST":
        raise ValueError("BUILDUID.S100_CRC_SCOPE")
    lower, upper = policy.coordinate_limits
    lines = ["  int day,month,year;", "  time_t secnow;", "  time(&secnow);",
             "  struct tm *tmptr=localtime(&secnow);",
             "  day=tmptr->tm_mday; month=tmptr->tm_mon+1; year=tmptr->tm_year-100;"]
    if policy.parse_wafer_slot:
        lines.extend((
            "  char wafer_id[2];", "  int wafer_num=0;", "  int flag=999;",
            "  for(int i=0;i<30;i++)", "  {",
            "    if((Sys_gszProberWaferID[i]==0X2D)&&(flag==999)&&(Sys_gszProberWaferID[i+1]>=0X30)&&(Sys_gszProberWaferID[i+1]<=0X39)&&(Sys_gszProberWaferID[i+2]>=0X30)&&(Sys_gszProberWaferID[i+2]<=0X39))",
            "    {", "      wafer_id[0]=Sys_gszProberWaferID[i+1];",
            "      wafer_id[1]=Sys_gszProberWaferID[i+2];", "      flag=0;",
            "    }", "  }", "  wafer_num=atoi(wafer_id);",
        ))
    lines.extend(("  for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)", "  {",
                  "    GB[0+T_SOCKET*64]=X_CO[T_SOCKET];",
                  f"    C_COMPARE(GB1,DOWN_LIMIT={lower},UP_LIMIT={upper},LOG_ALIAS=X_CO);",
                  "    GB[0+T_SOCKET*64]=Y_CO[T_SOCKET];",
                  f"    C_COMPARE(GB1,DOWN_LIMIT={lower},UP_LIMIT={upper},LOG_ALIAS=Y_CO);",
                  "  }", "  unsigned char ucPtr[14];",
                  "  for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)", "  {"))
    lines.extend(f"    ucPtr[{index}]={expression};" for index, expression in enumerate(policy.crc_inputs))
    lines.extend(("  }", "  unsigned char CRC8=GetCRC8(ucPtr,0x0E);",
                  "  for(T_SOCKET=0;T_SOCKET<Sys_TEST_DIE;T_SOCKET++)", "  {"))
    lines.extend(f"    {symbol}[T_SOCKET]={expression};" for symbol, expression in policy.word_expressions)
    lines.append("  }")
    return RecipeModuleEmission(statements=tuple(lines))


def render_build_uid_support(plan):
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
    return globals_text, helpers, "", ""
