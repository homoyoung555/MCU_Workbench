import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "tools" / "hex_to_pattern" / "profiles.json"
LEGACY_ROOT = ROOT / "tools" / "hex_to_pattern" / "legacy"

# 03_PatternConvert 中实际可由 HEX 驱动的 42 个主源：23 FBIST、2 SRAM、
# 16 SWD，以及根目录 PT103 扇区专项。另两个 C# 文件不是芯片下载器。
EXPECTED_SOURCES = {
    "PT103_Program_sector_test.cs",
    "_hex_to_chromapat/PCD101_hex_to_chromapat/PCD101_Program.cs",
    "_hex_to_chromapat/PT061_Btl_hex_to_chromapat/PT061_BootProgram.cs",
    "_hex_to_chromapat/PT061_hex_to_chromapat/PT061_Program.cs",
    "_hex_to_chromapat/PT063_hex_to_chromapat/PT063_Program.cs",
    "_hex_to_chromapat/PT067_hex_to_chromapat/PT067_Program.cs",
    "_hex_to_chromapat/PT068_hex_to_chromapat/PT068_Program.cs",
    "_hex_to_chromapat/PT088_Btl_hex_to_chromapat/PT088_BootProgram.cs",
    "_hex_to_chromapat/PT088_hex_to_chromapat/PT088_Program.cs",
    "_hex_to_chromapat/PT088_PageErase_Test/PageErase_Program.cs",
    "_hex_to_chromapat/PT088_SectorErase_Test/PT088_Sector.cs",
    "_hex_to_chromapat/PT100_hex_to_chromapat/PT100_Program.cs",
    "_hex_to_chromapat/PT102_Btl_hex_to_chromapat/PT102_BootProgram.cs",
    "_hex_to_chromapat/PT102_hex_to_chromapat/PT102_Program.cs",
    "_hex_to_chromapat/PT103_Bootloader_hex_to_chromapat/PT103_BootProgram.cs",
    "_hex_to_chromapat/PT103_hex_to_chromapat/PT103_Program.cs",
    "_hex_to_chromapat/PT104_Btl_hex_to_chromapat/PT104_btl_Program.cs",
    "_hex_to_chromapat/PT104_hex_to_chromapat/PT104_Program.cs",
    "_hex_to_chromapat/PT105_hex_to_chromapat/PT105_Program.cs",
    "_hex_to_chromapat/PT106_Btl_hex_to_chromapat/PT106_BootProgram.cs",
    "_hex_to_chromapat/PT106_hex_to_chromapat/PT106_Program.cs",
    "_hex_to_chromapat/PT107_hex_to_chromapat/PT107_Program.cs",
    "_hex_to_chromapat/PT108_hex_to_chromapat/PT108_Program.cs",
    "_hex_to_chromapat/_hex_to_chromapat/PT064_Program.cs",
    "_Hex_To_Sram_Pat/PT100_Hex_To_Sram_Pat/PT100_Program.cs",
    "_Hex_To_Sram_Pat/_Hex_To_Sram_Pat/PT067_Program.cs",
    "_hex_to_swdpat/PCD101_hex_to_swdpat/PCD101_Program.cs",
    "_hex_to_swdpat/PT061_HEX_TO_PAT/PT061_Program.cs",
    "_hex_to_swdpat/PT064_swd_hex_sd/PT064_sd.cs",
    "_hex_to_swdpat/PT067_hex_to_swd.sd/PT067_sd.cs",
    "_hex_to_swdpat/PT068_hex_to_swdpat/PT068_Program.cs",
    "_hex_to_swdpat/PT088_hex_to_blt_swdpat/PT088_Blt_Program.cs",
    "_hex_to_swdpat/PT088_hex_to_swdpat/PT088_Program.cs",
    "_hex_to_swdpat/PT102_hex_to_swdpat/PT102_Program.cs",
    "_hex_to_swdpat/PT103_hex_to_swdpat/PT103_Program.cs",
    "_hex_to_swdpat/PT104_hex_to_swdpat/PT104_Program.cs",
    "_hex_to_swdpat/PT105_hex_to_blt_swdpat/PT105_Blt_Program.cs",
    "_hex_to_swdpat/PT105_hex_to_swdpat/PT105_Program.cs",
    "_hex_to_swdpat/PT106_HEX_TO_PAT/PT106_Program.cs",
    "_hex_to_swdpat/PTXXX_hex_to_swdpat/PTXXX_Program.cs",
    "_hex_to_swdpat/_hex_to_swd.sd/PT061_sd.cs",
    "_hex_to_swdpat/_hex_to_swdpat/Program.cs",
}

NON_PROFILE_SOURCES = {
    "ChromaPat_TO_S100Sd/ChromaPat_TO_S100Sd/Program.cs",
    "_hex_to_swdpat/ConsoleApp1/Program.cs",
}

REQUIRED_FIELDS = {
    "id",
    "chip",
    "label",
    "mode",
    "platform",
    "source",
    "pins",
    "timeset",
    "pageSize",
    "verify",
    "erase",
    "enabled",
    "reason",
    "maxAddress",
    "supportsExtended64k",
}


def load_profiles():
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def test_profiles_are_complete_unique_and_backed_by_legacy_sources():
    profiles = load_profiles()

    assert len(profiles) == 42
    assert {profile["source"] for profile in profiles} == EXPECTED_SOURCES
    assert len({profile["id"] for profile in profiles}) == len(profiles)

    actual_sources = {
        path.relative_to(LEGACY_ROOT).as_posix()
        for path in LEGACY_ROOT.rglob("*.cs")
    }
    assert actual_sources == EXPECTED_SOURCES | NON_PROFILE_SOURCES
    assert all((LEGACY_ROOT / profile["source"]).is_file() for profile in profiles)


def test_profile_schema_and_catalogue_constraints():
    profiles = load_profiles()
    for profile in profiles:
        assert set(profile) == REQUIRED_FIELDS
        assert re.fullmatch(r"[a-z0-9-]+", profile["id"])
        assert profile["mode"] in {"fbist_flash", "swd_flash", "swd_sram"}
        assert profile["platform"] in {"chroma", "s100"}
        assert profile["pins"] and all(isinstance(pin, str) for pin in profile["pins"])
        assert profile["timeset"] is None or re.fullmatch(r"TS[0-9]+", profile["timeset"])
        assert isinstance(profile["pageSize"], int) and profile["pageSize"] > 0
        assert isinstance(profile["verify"], bool)
        assert isinstance(profile["erase"], str) and profile["erase"]
        assert isinstance(profile["enabled"], bool)
        assert profile["reason"] is None if profile["enabled"] else isinstance(profile["reason"], str)
        assert profile["maxAddress"] is None or profile["maxAddress"] > 0
        assert isinstance(profile["supportsExtended64k"], bool)

    assert sum(profile["mode"] == "fbist_flash" for profile in profiles) == 24
    assert sum(profile["mode"] == "swd_sram" for profile in profiles) == 2
    assert sum(profile["mode"] == "swd_flash" for profile in profiles) == 16


def test_critical_source_derived_characteristics():
    profiles = {profile["id"]: profile for profile in load_profiles()}

    assert profiles["fbist-pt104-flash"]["pins"] == ["PA11", "PA13", "NRST"]
    assert profiles["swd-pt104-flash"]["pins"] == ["PA14", "PA13", "PF5"]
    assert profiles["swd-pt104-flash"]["verify"] is False
    assert profiles["fbist-pt088-page-erase"]["verify"] is False
    assert profiles["swd-pcd101-flash"]["supportsExtended64k"] is True
    assert profiles["swd-pt061-s100"]["timeset"] is None
    assert profiles["swd-pt064-s100"]["platform"] == "s100"
    assert profiles["swd-sram-pt067"]["pageSize"] == 4
    assert profiles["swd-sram-pt100"]["pageSize"] == 4

    ptxxx = profiles["swd-ptxxx-template"]
    assert ptxxx["enabled"] is False
    assert "注释" in ptxxx["reason"]

    assert profiles["fbist-pt105-flash"]["enabled"] is False
    assert profiles["swd-pt102-flash"]["enabled"] is False

    generic = profiles["swd-unlabeled-generic"]
    assert generic["chip"] == "UNSPECIFIED"
    assert generic["enabled"] is False


def test_critical_flags_have_source_evidence():
    def source(profile_id):
        return (LEGACY_ROOT / profiles[profile_id]["source"]).read_text(encoding="utf-8")

    profiles = {profile["id"]: profile for profile in load_profiles()}
    assert 'Addroffset = 0x10000' in source("swd-pcd101-flash")
    assert 'Addroffset = 0x10000' in source("swd-pt104-flash")
    assert '//Read_pat(sw, line, InitialStr);' in source("fbist-pt088-page-erase")

    pt105 = source("fbist-pt105-flash")
    assert '/*\n            while ((line = sr.ReadLine()) != null)' in pt105
    assert 'Read_bank0_pat(sw, line, InitialStr);' in pt105

    pt102 = source("swd-pt102-flash")
    assert '/*\n            SWD_Write_Addr' in pt102
    assert 'Read_pat(sw, line, InitialStr);' in pt102

    ptxxx = source("swd-ptxxx-template")
    assert '/*\n            SWD_Mass_Erase' in ptxxx

    sram = source("swd-sram-pt067")
    assert 'SramStartAddr = 0x20000000' in sram
    assert 'addr + j + SramStartAddr' in sram
