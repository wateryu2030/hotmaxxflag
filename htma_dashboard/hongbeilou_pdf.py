# -*- coding: utf-8 -*-
"""供销社红背篓选品单 PDF（中文表头、可选水印、时效声明）。"""
from io import BytesIO
from decimal import Decimal


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, Decimal):
        return str(float(v))
    if isinstance(v, float):
        if v != v:  # nan
            return ""
        return str(round(v, 4)) if abs(v - int(v)) > 1e-9 else str(int(v))
    return str(v)


def _one_line_fit(text, font_name, font_size, max_inner_width):
    """
    单行展示：去换行，过长按 STSong 宽度截断加省略号，避免单元格内折行。
    max_inner_width：扣除左右内边距后的可用宽度（pt）。
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth

    s = (text or "").replace("\n", " ").replace("\r", " ").strip()
    if not s:
        return ""
    if max_inner_width <= 6:
        return s[:1] + "…" if len(s) > 1 else s
    if stringWidth(s, font_name, font_size) <= max_inner_width:
        return s
    ell = "…"
    ell_w = stringWidth(ell, font_name, font_size)
    budget = max_inner_width - ell_w
    if budget <= 0:
        return ell
    lo, hi = 0, len(s)
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        prefix = s[:mid]
        if stringWidth(prefix, font_name, font_size) <= budget:
            best = prefix
            lo = mid + 1
        else:
            hi = mid - 1
    if not best:
        return ell
    return best + ell


# 与「序号 + EXPORT_SIMPLE_COLUMNS」列顺序对应的相对权重（总和=1），品名列最宽
_PDF_COL_WEIGHTS = [
    0.05,  # 序号
    0.28,  # 品名
    0.12,  # 规格
    0.05,  # 单位
    0.10,  # 品牌
    0.11,  # 中类
    0.11,  # 小类
    0.08,  # 库存数量
    0.05,  # 近30天销量
    0.05,  # 供货价
]


def _make_watermark_canvas_class(wm_text):
    """
    在每页调用 showPage 时先叠加水印，再翻页；这样水印在表格内容之上可见
    （onFirstPage 早于 flowable 绘制，会被表格底色盖住）。
    """
    from reportlab.pdfgen import canvas as pdfcanvas

    class WatermarkCanvas(pdfcanvas.Canvas):
        def __init__(self, *args, **kwargs):
            self._wm_text = wm_text or ""
            pdfcanvas.Canvas.__init__(self, *args, **kwargs)

        def showPage(self):
            if self._wm_text:
                self.saveState()
                try:
                    self.setFillAlpha(0.28)
                except Exception:
                    pass
                self.setFillColorRGB(0.48, 0.48, 0.48)
                w, h = self._pagesize
                self.setFont("STSong-Light", 40)
                self.translate(w / 2, h / 2)
                self.rotate(35)
                self.drawCentredString(0, 0, self._wm_text)
                self.restoreState()
            pdfcanvas.Canvas.showPage(self)

    return WatermarkCanvas


def render_hongbeilou_pdf_bytes(
    simple_rows,
    column_defs,
    title="供销社「红背篓」选品单",
    disclaimer_lines=None,
    watermark=False,
    watermark_text="宝赞商业＠振鸿",
):
    """
    column_defs: [(field_key, zh_header), ...] 与 CSV 数据列一致（不含序号，序号由本函数首列自动生成）
    simple_rows: list of dict with same keys as field_key
    Returns PDF bytes or raises ImportError / Exception from reportlab.

    版式：除第 2 列（品名）左对齐外其余列居中；单元格强制单行（过长截断）；列宽按权重分配。
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    font = "STSong-Light"
    table_font_size = 8
    header_font_size = 8
    cell_pad_lr = 3
    cell_pad_tb = 3

    buf = BytesIO()
    wm_str = (watermark_text or "宝赞商业＠振鸿").replace("@", "＠")
    doc_kw = {}
    if watermark:
        doc_kw["canvasmaker"] = _make_watermark_canvas_class(wm_str)

    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        **doc_kw,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "t",
        parent=styles["Title"],
        fontName=font,
        fontSize=14,
        leading=18,
    )
    body_style = ParagraphStyle(
        "b",
        parent=styles["Normal"],
        fontName=font,
        fontSize=9,
        leading=12,
    )

    story = []
    story.append(Paragraph(title.replace("<", "&lt;"), title_style))
    story.append(Spacer(1, 6))

    ncols = 1 + len(column_defs)
    weights = _PDF_COL_WEIGHTS[:ncols]
    if len(weights) != ncols:
        # 列数变化时退回均分，避免索引错误
        weights = [1.0 / ncols] * ncols
    wsum = sum(weights)
    table_total_w = doc.width - 20
    tw = [table_total_w * (w / wsum) for w in weights]

    def inner_w(col_idx):
        return max(4.0, tw[col_idx] - 2 * cell_pad_lr)

    headers_raw = ["序号"] + [h for _k, h in column_defs]
    header_cells = [
        _one_line_fit(h, font, header_font_size, inner_w(j)) for j, h in enumerate(headers_raw)
    ]

    data = [header_cells]
    for i, row in enumerate(simple_rows, start=1):
        cells = [_one_line_fit(str(i), font, table_font_size, inner_w(0))]
        for j, (k, _h) in enumerate(column_defs, start=1):
            cells.append(_one_line_fit(_cell(row.get(k)), font, table_font_size, inner_w(j)))
        data.append(cells)

    nrows = len(data)
    header_row_h = header_font_size + 2 * cell_pad_tb + 6
    body_row_h = table_font_size + 2 * cell_pad_tb + 6
    row_heights = [header_row_h] + [body_row_h] * (nrows - 1)

    tbl = Table(data, colWidths=tw, rowHeights=row_heights, repeatRows=1)

    ts_cmds = [
        ("FONT", (0, 0), (-1, 0), font, header_font_size),
        ("FONT", (0, 1), (-1, -1), font, table_font_size),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("LEFTPADDING", (0, 0), (-1, -1), cell_pad_lr),
        ("RIGHTPADDING", (0, 0), (-1, -1), cell_pad_lr),
        ("TOPPADDING", (0, 0), (-1, -1), cell_pad_tb),
        ("BOTTOMPADDING", (0, 0), (-1, -1), cell_pad_tb),
        # 第 2 列（索引 1，品名）左对齐；其余列居中（含序号）
        ("ALIGN", (1, 0), (1, -1), "LEFT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
    ]
    if ncols > 2:
        ts_cmds.append(("ALIGN", (2, 0), (-1, -1), "CENTER"))

    tbl.setStyle(TableStyle(ts_cmds))
    story.append(tbl)
    story.append(Spacer(1, 10))

    if disclaimer_lines:
        for line in disclaimer_lines:
            story.append(Paragraph(line.replace("<", "&lt;"), body_style))
            story.append(Spacer(1, 4))

    doc.build(story)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes
