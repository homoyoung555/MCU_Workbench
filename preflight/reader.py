# Canonical WorkbookModel 只读视图：把同一母本快照暴露为
# "带单元格坐标 + 数据类型 + 数字格式"的 preflight 单元格流。所有 provenance
# 已由 WorkbookReader 保留；本模块不重新打开 Excel。
from openpyxl.utils import get_column_letter

from program_gen.workbook import WorkbookModel, WorkbookReader


class Cell:
    """一个数据单元格的快照。"""
    __slots__ = ("sheet", "row", "col", "header", "coord", "value", "dtype", "numfmt")

    def __init__(self, sheet, row, col, header, value, dtype, numfmt):
        self.sheet = sheet
        self.row = row                       # 1-based Excel 行号
        self.col = col                       # 1-based 列号
        self.header = header                 # 列名
        self.coord = get_column_letter(col) + str(row)   # 如 "Q40"
        self.value = value                   # 单元格值（文本=str，数字=int/float，空=None）
        self.dtype = dtype                   # openpyxl data_type: 's'文本 'n'数字 'b'布尔 ...
        self.numfmt = numfmt                 # 数字格式串（detect 全角%/百分比格式用）

    @property
    def text(self):
        """值转字符串（None→""），用于字符卫生等文本检查。"""
        return "" if self.value is None else str(self.value)

    @property
    def is_blank(self):
        return self.value is None or (isinstance(self.value, str) and self.value.strip() == "")


class MasterReader:
    """读母本 xlsx，按 sheet/列名提供单元格流。header 固定在第 1 行。"""

    def __init__(self, source):
        self.wb = source if isinstance(source, WorkbookModel) else WorkbookReader().read(source)
        self.path = self.wb.source_path
        self.sheetnames = list(self.wb.sheetnames)
        self._hdr_cache = {}

    def has_sheet(self, sheet):
        return sheet in self.wb.sheetnames

    def header_map(self, sheet):
        """{列名: 列号(1-based)}，取第 1 行。重复列名保留首个。"""
        if sheet in self._hdr_cache:
            return self._hdr_cache[sheet]
        ws = self.wb[sheet]
        m = {}
        for c, cell in enumerate(next(ws.iter_rows(min_row=1, max_row=1)), start=1):
            name = cell.value
            if name is not None and str(name).strip() != "" and str(name) not in m:
                m[str(name)] = c
        self._hdr_cache[sheet] = m
        return m

    @staticmethod
    def _mk(sheet, rownum, col, header, cell):
        # read_only 模式空格是 EmptyCell（无 .data_type/.number_format/.row）；用 getattr 兜底。
        if cell is None:
            return Cell(sheet, rownum, col, header, None, None, None)
        return Cell(sheet, rownum, col, header, getattr(cell, "value", None),
                    getattr(cell, "data_type", None), getattr(cell, "number_format", None))

    def column_cells(self, sheet, header):
        """某列所有数据行(从第 2 行起)的 Cell 列表；列不存在回 []。"""
        hm = self.header_map(sheet)
        if header not in hm:
            return []
        col = hm[header]
        ws = self.wb[sheet]
        out = []
        for rownum, row in enumerate(ws.iter_rows(min_row=2), start=2):
            cell = row[col - 1] if col - 1 < len(row) else None
            out.append(self._mk(sheet, rownum, col, header, cell))
        return out

    def row_values(self, sheet, headers):
        """按行返回 {列名: Cell}，只取 headers 里的列；用于跨列/整行检查(如空行)。"""
        hm = self.header_map(sheet)
        cols = {h: hm[h] for h in headers if h in hm}
        ws = self.wb[sheet]
        for rownum, row in enumerate(ws.iter_rows(min_row=2), start=2):
            rec = {h: self._mk(sheet, rownum, c, h, row[c - 1] if c - 1 < len(row) else None)
                   for h, c in cols.items()}
            yield rec

    def frame(self, sheet):
        """Return a private dataframe projection from the same WorkbookModel."""
        return self.wb.dataframe(sheet)

    def close(self):
        self.wb.close()
