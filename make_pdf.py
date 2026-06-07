"""
make_pdf.py  —  Convert device_integration_guide.md → device_integration_guide.pdf
Run: python make_pdf.py
"""
import re
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                 Preformatted, HRFlowable, PageBreak,
                                 Table, TableStyle)
from reportlab.lib.enums import TA_LEFT, TA_CENTER

SRC  = r'docs\device_integration_guide.md'
DEST = r'docs\device_integration_guide.pdf'

# ── Colours ───────────────────────────────────────────────────
PRI    = colors.HexColor('#1b4332')
PRI2   = colors.HexColor('#2d6a4f')
LIGHT  = colors.HexColor('#f0f7f4')
CODEBG = colors.HexColor('#f4f4f4')
MUTED  = colors.HexColor('#555555')

# ── Styles ────────────────────────────────────────────────────
def style(name, **kw):
    return ParagraphStyle(name, **kw)

sTitle  = style('sTitle',  fontName='Helvetica-Bold',  fontSize=28, textColor=PRI,
                leading=34, spaceAfter=10, alignment=TA_CENTER)
sSub2   = style('sSub2',   fontName='Helvetica-Bold',  fontSize=20, textColor=PRI,
                leading=25, spaceAfter=10, alignment=TA_CENTER)
sSub    = style('sSub',    fontName='Helvetica',        fontSize=11, textColor=MUTED,
                leading=16, spaceAfter=30, alignment=TA_CENTER)
sH1     = style('sH1',     fontName='Helvetica-Bold',  fontSize=18, textColor=PRI,
                leading=22, spaceBefore=18, spaceAfter=6)
sH2     = style('sH2',     fontName='Helvetica-Bold',  fontSize=13, textColor=PRI,
                leading=17, spaceBefore=14, spaceAfter=4)
sH3     = style('sH3',     fontName='Helvetica-Bold',  fontSize=11, textColor=PRI2,
                leading=15, spaceBefore=10, spaceAfter=3)
sH4     = style('sH4',     fontName='Helvetica-BoldOblique', fontSize=10, textColor=PRI2,
                leading=14, spaceBefore=8,  spaceAfter=2)
sBody   = style('sBody',   fontName='Helvetica',       fontSize=9.5, leading=14, spaceAfter=4)
sBullet = style('sBullet', fontName='Helvetica',       fontSize=9.5, leading=13,
                leftIndent=14, spaceAfter=2)
sBQ     = style('sBQ',     fontName='Helvetica-Oblique', fontSize=9.5, leading=13,
                leftIndent=16, spaceAfter=4, textColor=colors.HexColor('#444'))
sCode   = style('sCode',   fontName='Courier',         fontSize=8.0, leading=11.5,
                backColor=CODEBG, leftIndent=8, rightIndent=8,
                spaceBefore=4, spaceAfter=6,
                borderPad=4)
sTH = style('sTH', fontName='Helvetica-Bold', fontSize=8.5, leading=12,
            textColor=colors.white, alignment=TA_CENTER)
sTD = style('sTD', fontName='Helvetica',      fontSize=8.2, leading=12)

# ── Inline formatting ─────────────────────────────────────────
def fmt(text):
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*([^*]+?)\*',  r'<i>\1</i>', text)
    text = re.sub(r'`([^`]+)`', r'<font face="Courier" size="8.5">\1</font>', text)
    text = text.replace('—', '&mdash;')
    text = text.replace('→', '&#8594;')
    text = text.replace('↓', '&#8595;')
    text = text.replace('✅', '[OK]')
    text = text.replace('❌', '[ERR]')
    text = text.replace('☑', '[x]')
    text = text.replace('☐', '[ ]')
    text = text.replace('🐾', '')
    return text

# ── Parse ─────────────────────────────────────────────────────
with open(SRC, encoding='utf-8') as f:
    lines = f.readlines()

doc = SimpleDocTemplate(
    DEST, pagesize=A4,
    leftMargin=2.2*cm, rightMargin=2.2*cm,
    topMargin=2.2*cm,  bottomMargin=2.2*cm,
    title='SmartPetHome Device Integration Guide',
    author='SmartPetTec'
)

story = []

# ── Title page ────────────────────────────────────────────────
story.append(Spacer(1, 3*cm))
story.append(Paragraph('SmartPetHome', sTitle))
story.append(Paragraph('Device Integration Guide', sSub2))
story.append(HRFlowable(width='80%', thickness=2, color=PRI, spaceBefore=8, spaceAfter=12))
story.append(Paragraph('Sprint 2 &mdash; For developers and AI agents integrating ESP32 hardware', sSub))
story.append(PageBreak())

# ── Line-by-line parse ────────────────────────────────────────
in_code  = False
code_buf = []
in_table = False
tbl_rows = []

def flush_code():
    if code_buf:
        raw = '\n'.join(code_buf)
        story.append(Preformatted(raw, sCode))
        code_buf.clear()

def flush_table():
    if not tbl_rows:
        return
    data = [r for r in tbl_rows
            if not all(re.match(r'^[-: ]+$', c.strip()) for c in r)]
    if not data:
        tbl_rows.clear()
        return

    col_n = max(len(r) for r in data)

    def cell(text, header=False):
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text.strip())
        text = re.sub(r'`([^`]+)`', r'<font face="Courier" size="7.5">\1</font>', text)
        text = text.replace('→', '&#8594;')
        return Paragraph(text, sTH if header else sTD)

    table_data = []
    for ri, row in enumerate(data):
        while len(row) < col_n:
            row.append('')
        table_data.append([cell(c, header=(ri == 0)) for c in row])

    col_w = doc.width / col_n
    t = Table(table_data, colWidths=[col_w] * col_n, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND',  (0, 0), (-1, 0),  PRI),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT]),
        ('GRID',        (0, 0), (-1, -1), 0.4, colors.HexColor('#cccccc')),
        ('VALIGN',      (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING',(0, 0), (-1, -1), 5),
        ('TOPPADDING',  (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING',(0,0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 6))
    tbl_rows.clear()

for raw_line in lines:
    line = raw_line.rstrip('\n')

    # ── Code fence ───────────────────────────────────────────
    if line.strip().startswith('```'):
        if in_code:
            flush_code()
            in_code = False
        else:
            in_code = True
        continue

    if in_code:
        code_buf.append(line)
        continue

    # ── Table ────────────────────────────────────────────────
    if line.startswith('|'):
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        tbl_rows.append(cells)
        in_table = True
        continue
    elif in_table:
        flush_table()
        in_table = False

    stripped = line.strip()

    if not stripped:
        story.append(Spacer(1, 4))
        continue

    # ── Headings ─────────────────────────────────────────────
    m = re.match(r'^(#{1,4})\s+(.*)', stripped)
    if m:
        lvl = len(m.group(1))
        txt = fmt(m.group(2))
        if lvl == 1:
            story.append(HRFlowable(width='100%', thickness=1,
                                     color=colors.HexColor('#d0e8d8'),
                                     spaceBefore=8, spaceAfter=4))
            story.append(Paragraph(txt, sH1))
        elif lvl == 2:
            story.append(Paragraph(txt, sH2))
        elif lvl == 3:
            story.append(Paragraph(txt, sH3))
        else:
            story.append(Paragraph(txt, sH4))
        continue

    # ── HR ────────────────────────────────────────────────────
    if re.match(r'^-{3,}$', stripped):
        story.append(HRFlowable(width='100%', thickness=0.5,
                                 color=colors.HexColor('#ccc'),
                                 spaceBefore=4, spaceAfter=4))
        continue

    # ── Bullet ───────────────────────────────────────────────
    m2 = re.match(r'^[-*]\s+(\[[ xX]\]\s+)?(.*)', stripped)
    if m2:
        check = m2.group(1) or ''
        txt = fmt(m2.group(2))
        prefix = '[x] ' if re.search(r'[xX]', check) else ('[ ] ' if check else '• ')
        story.append(Paragraph(prefix + txt, sBullet))
        continue

    # ── Numbered list ────────────────────────────────────────
    m3 = re.match(r'^\d+\.\s+(.*)', stripped)
    if m3:
        story.append(Paragraph('• ' + fmt(m3.group(1)), sBullet))
        continue

    # ── Blockquote ───────────────────────────────────────────
    if stripped.startswith('>'):
        story.append(Paragraph(fmt(stripped.lstrip('> ')), sBQ))
        continue

    # ── Normal paragraph ─────────────────────────────────────
    story.append(Paragraph(fmt(stripped), sBody))

if in_table:
    flush_table()
if in_code:
    flush_code()

doc.build(story)
print(f'Done: {DEST}')
