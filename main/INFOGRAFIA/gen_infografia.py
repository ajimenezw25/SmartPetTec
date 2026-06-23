from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER, TA_LEFT

OUTPUT    = "B:/TEC/SmartPetTec/SmartPetTec/main/INFOGRAFIA/infografia.pdf"
LOGO_PATH = "B:/Pictures/Screenshots/Captura de pantalla 2026-06-23 130853.png"

W, H = A4  # 595 x 842 pts

doc = SimpleDocTemplate(
    OUTPUT,
    pagesize=A4,
    leftMargin=1.6*cm,
    rightMargin=1.6*cm,
    topMargin=1.4*cm,
    bottomMargin=1.4*cm,
)

# ── Colors ────────────────────────────────────────────────
TEAL_BG   = colors.HexColor("#E1F5EE")
TEAL_FG   = colors.HexColor("#0F6E56")
PURPLE_BG = colors.HexColor("#EEEDFE")
PURPLE_FG = colors.HexColor("#3C3489")
AMBER_BG  = colors.HexColor("#FAEEDA")
AMBER_FG  = colors.HexColor("#854F0B")
GRAY_LINE = colors.HexColor("#D3D1C7")
DARK      = colors.HexColor("#1A1A1A")
MID       = colors.HexColor("#444444")
MUTED     = colors.HexColor("#888888")
WHITE     = colors.white

# ── Styles ────────────────────────────────────────────────
title_st = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=24,
                           textColor=DARK, alignment=TA_CENTER, spaceAfter=6)
retro_st = ParagraphStyle("retro", fontName="Helvetica", fontSize=13,
                           textColor=MUTED, alignment=TA_CENTER, spaceBefore=4, spaceAfter=0)
card_ttl = ParagraphStyle("ctitle", fontName="Helvetica-Bold", fontSize=13,
                           textColor=DARK, alignment=TA_CENTER, spaceAfter=4, spaceBefore=8)
bullet_st = ParagraphStyle("bullet", fontName="Helvetica", fontSize=10.5,
                            textColor=MID, leading=16, leftIndent=4, spaceAfter=2)
name_st  = ParagraphStyle("name", fontName="Helvetica", fontSize=10,
                           textColor=MID, alignment=TA_CENTER, leading=16)
name_ttl = ParagraphStyle("namettl", fontName="Helvetica-Bold", fontSize=12,
                           textColor=DARK, alignment=TA_CENTER, spaceAfter=10, spaceBefore=6)

# ── Section data ──────────────────────────────────────────
sections = [
    {
        "tag": "Lo que se logro",
        "tag_bg": TEAL_BG, "tag_fg": TEAL_FG,
        "title": "Conclusiones",
        "bullets": [
            "Sistema funcional ESP32 -> MQTT -> Flask -> Supabase -> UI",
            "Comunicacion en tiempo real entre hardware y app web",
            "Registro y visualizacion de telemetria de dispositivos",
            "Autenticacion de usuarios y gestion de mascotas",
            "Ejecutable de escritorio con PyInstaller",
            "Los 8 tipos de dispositivos fueron implementados y probados",
        ]
    },
    {
        "tag": "Lo que aprendimos",
        "tag_bg": PURPLE_BG, "tag_fg": PURPLE_FG,
        "title": "Aprendizajes",
        "bullets": [
            "Integrar ESP32 con la nube requiere mas trabajo del esperado",
            "MQTT es ideal para IoT: ligero y asincrono",
            "Supabase acelera el backend con DB + auth incluidos",
            "El broker publico EMQX funciona bien para prototipos",
            "Depurar el ESP32 via Serial acelera el ciclo de desarrollo antes de conectar a la nube",
        ]
    },
    {
        "tag": "Para el futuro",
        "tag_bg": AMBER_BG, "tag_fg": AMBER_FG,
        "title": "Que mejorar",
        "bullets": [
            "Usar broker MQTT privado con TLS en produccion",
            "Anadir notificaciones push en tiempo real",
            "App movil nativa en lugar de solo web",
            "Reportes historicos y analisis de datos avanzados",
            "Pruebas automatizadas de integracion hardware-software",
        ]
    },
]

# Card width: (17.4cm usable / 3) - gaps
CARD_W = 5.7 * cm

def make_tag(text, bg, fg):
    p = Paragraph(text, ParagraphStyle("tg", fontName="Helvetica-Bold",
                  fontSize=9.5, textColor=fg, alignment=TA_CENTER))
    t = Table([[p]], colWidths=[CARD_W - 0.6*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND",   (0,0),(-1,-1), bg),
        ("TOPPADDING",   (0,0),(-1,-1), 5),
        ("BOTTOMPADDING",(0,0),(-1,-1), 5),
        ("LEFTPADDING",  (0,0),(-1,-1), 8),
        ("RIGHTPADDING", (0,0),(-1,-1), 8),
    ]))
    return t

def build_card(sec):
    rows = []
    rows.append([make_tag(sec["tag"], sec["tag_bg"], sec["tag_fg"])])
    rows.append([Paragraph(sec["title"], card_ttl)])
    for b in sec["bullets"]:
        rows.append([Paragraph(f"→  {b}", bullet_st)])

    card = Table(rows, colWidths=[CARD_W])
    style = [
        ("BACKGROUND",   (0,0),(-1,-1), WHITE),
        ("BOX",          (0,0),(-1,-1), 0.5, GRAY_LINE),
        ("TOPPADDING",   (0,0),(-1,-1), 8),
        ("BOTTOMPADDING",(0,0),(-1,-1), 8),
        ("LEFTPADDING",  (0,0),(-1,-1), 12),
        ("RIGHTPADDING", (0,0),(-1,-1), 12),
        ("VALIGN",       (0,0),(-1,-1), "TOP"),
    ]
    for i in range(2, len(rows) - 1):
        style.append(("LINEBELOW", (0,i), (-1,i), 0.4, GRAY_LINE))
    card.setStyle(TableStyle(style))
    return card

# ── Build story ───────────────────────────────────────────
story = []

# Header
logo    = Image(LOGO_PATH, width=5.5*cm, height=1.55*cm)
title_p = Paragraph("SmartPetHome", title_st)
retro_p = Paragraph("Retrospectiva", retro_st)

header = Table(
    [[logo, [title_p, retro_p]]],
    colWidths=[5.5*cm, 11.9*cm],
    hAlign="LEFT",
)
header.setStyle(TableStyle([
    ("VALIGN",       (0,0),(-1,-1), "MIDDLE"),
    ("LEFTPADDING",  (0,0),(-1,-1), 0),
    ("RIGHTPADDING", (0,0),(-1,-1), 0),
    ("TOPPADDING",   (0,0),(-1,-1), 0),
    ("BOTTOMPADDING",(0,0),(-1,-1), 0),
]))
story.append(header)
story.append(Spacer(1, 0.35*cm))
story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY_LINE, spaceAfter=14))

# Cards grid
cards = [build_card(s) for s in sections]
grid = Table(
    [cards],
    colWidths=[CARD_W, CARD_W, CARD_W],
    hAlign="CENTER",
)
grid.setStyle(TableStyle([
    ("VALIGN",       (0,0),(-1,-1), "TOP"),
    ("LEFTPADDING",  (0,0),(-1,-1), 4),
    ("RIGHTPADDING", (0,0),(-1,-1), 4),
    ("TOPPADDING",   (0,0),(-1,-1), 0),
    ("BOTTOMPADDING",(0,0),(-1,-1), 0),
]))
story.append(grid)
story.append(Spacer(1, 0.8*cm))
story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY_LINE, spaceAfter=12))

# Team members
story.append(Paragraph("Integrantes del equipo", name_ttl))
members = [
    ("Alejandro Jimenez Wilhelm", "2022173424"),
    ("Yherland Elizondo Cordero", "2022289492"),
    ("Isaac Somarribas Montero",  "2020125516"),
    ("Isac Marin Sirias",         "2021135407"),
]
member_cells = [
    [Paragraph(f"<b>{n}</b><br/>{c}", name_st)] for n, c in members
]
team_table = Table(
    [member_cells],
    colWidths=[4.35*cm] * 4,
    hAlign="CENTER",
)
team_table.setStyle(TableStyle([
    ("VALIGN",       (0,0),(-1,-1), "MIDDLE"),
    ("LEFTPADDING",  (0,0),(-1,-1), 6),
    ("RIGHTPADDING", (0,0),(-1,-1), 6),
    ("TOPPADDING",   (0,0),(-1,-1), 8),
    ("BOTTOMPADDING",(0,0),(-1,-1), 8),
    ("LINEAFTER",    (0,0),(2,0), 0.4, GRAY_LINE),
    ("BOX",          (0,0),(-1,-1), 0.5, GRAY_LINE),
]))
story.append(team_table)

doc.build(story)
print("PDF generado:", OUTPUT)
