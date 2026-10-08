# Project Map

## Project

- Root: `D:\Code\03_offline_mcu_ate\chroma_to_s100\cache\encoding_v2\py32f420`
- Repository: `D:\Code\03_offline_mcu_ate\chroma_to_s100`
- Active branch at inspection: `main`
- Purpose: encoded/offline PY32F420 MCU reference material used to diagnose the CP IWDG test.

## Structure

- `.Codex/PROJECT_MAP.md`: concise project map (this file).
- `fieldmap.json`: register fields, masks, reset/access metadata, and semantic notes.
- `iwdg_encoding.json`: IWDG prescaler and reload configuration encodings.
- `flash_encoding.json`: Flash/Option Byte encodings, including `OPTR1.IWDG_SW`.
- `rcc_encoding.json`: RCC and LSI configuration encodings.
- `reset_gaps.json`: peripheral register/reset coverage inventory.
- `REVIEW.md`: generated human-readable encoding review.

## Architecture and relationships

- IWDG uses `KR/PR/RLR/SR`; `PR=0` means divide-by-4 and `SR.PVU/RVU` report asynchronous updates.
- `FLASH.OPTR1.IWDG_SW` is bit 14: `0` hardware mode, `1` software mode.
- `FLASH.CR.OBL_LAUNCH` is bit 27 and requests a system reset plus option-byte reload.
- This cache supplies register semantics for the CP firmware in `D:\Code\0x_代码分析\temp`.
