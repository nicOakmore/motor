"""
catalogue_seed.py — Generate the demo price catalogue + concept metadata.

This is a SYNTHETIC catalogue structured like BEDEC (FIEBDC-3 / ITeC):
each partida has a code, a chapter, a description, a unit, a mo/mat/maq
breakdown and a unit price. Prices are illustrative Spanish 2024-2026
mid-range figures, NOT real BEDEC/CYPE/PREOC data.

Real production: replace `precios/precios_ibiza_2026.csv` with the firm's
own negotiated prices and/or a licensed BEDEC export.

Run:
    python catalogue_seed.py
…produces:
    precios/precios_ibiza_2026.csv     (the price catalogue)
    precios/materiales_unitarios.csv   (per-partida material ratios)
    _catalogue_seed.json               (concepto → {price_code, capitulo, unidad})

The JSON output is read by `rules.json` build step / runner so the engine
knows which price code each scope-item concept resolves to.
"""

from __future__ import annotations
import csv
import json
import pathlib

ROOT = pathlib.Path(__file__).parent

# (chapter_code, chapter_name, mo_pct, mat_pct, maq_pct, indir_pct)
# Cost-breakdown ratios per chapter, applied uniformly inside each chapter.
CHAPTER_RATIOS: dict[str, tuple[str, float, float, float, float]] = {
    "DEM": ("Demoliciones",                0.80, 0.05, 0.15, 0.06),
    "TER": ("Movimiento de tierras",       0.35, 0.05, 0.60, 0.06),
    "CIM": ("Cimentación",                 0.25, 0.60, 0.15, 0.06),
    "EST": ("Estructura",                  0.30, 0.60, 0.10, 0.06),
    "CUB": ("Cubiertas",                   0.45, 0.50, 0.05, 0.06),
    "ALB": ("Albañilería",                 0.55, 0.40, 0.05, 0.06),
    "AIS": ("Aislamientos e impermeabilizaciones", 0.45, 0.55, 0.00, 0.06),
    "REV": ("Revestimientos",              0.55, 0.42, 0.03, 0.06),
    "PAV": ("Pavimentos",                  0.40, 0.55, 0.05, 0.06),
    "CRI": ("Carpintería interior",        0.30, 0.70, 0.00, 0.06),
    "CRE": ("Carpintería exterior",        0.30, 0.70, 0.00, 0.06),
    "PIN": ("Pintura",                     0.60, 0.40, 0.00, 0.06),
    "FON": ("Fontanería",                  0.35, 0.65, 0.00, 0.06),
    "SAN": ("Saneamiento",                 0.35, 0.65, 0.00, 0.06),
    "ELE": ("Electricidad",                0.40, 0.60, 0.00, 0.06),
    "CLI": ("Climatización",               0.25, 0.75, 0.00, 0.06),
    "URB": ("Urbanización y exteriores",   0.40, 0.50, 0.10, 0.06),
}

# Canonical chapter order for budgets and plan de obra.
CHAPTER_ORDER = [
    "Demoliciones", "Movimiento de tierras", "Cimentación", "Estructura",
    "Cubiertas", "Albañilería", "Aislamientos e impermeabilizaciones",
    "Revestimientos", "Pavimentos", "Carpintería interior",
    "Carpintería exterior", "Pintura", "Fontanería", "Saneamiento",
    "Electricidad", "Climatización", "Urbanización y exteriores",
]

# (chapter_code, n_within_chapter, concept_key, unidad, total_eur, description)
# concept_key is what the parser detects from the memoria; it's also the
# JSON key in concepto_metadata.
PARTIDAS: list[tuple[str, int, str, str, float, str]] = [
    # Demoliciones
    ("DEM", 1, "demolicion_tabique_lhd",      "m2",    15.40, "Demolición de tabique de ladrillo hueco doble, incluso retirada de escombros"),
    ("DEM", 2, "demolicion_tabique_lh7",       "m2",     9.80, "Demolición de tabique de ladrillo hueco simple LH7"),
    ("DEM", 3, "demolicion_muro_fabrica",      "m3",    65.00, "Demolición de muro de fábrica de espesor > 15 cm, por medios manuales"),
    ("DEM", 4, "levantado_solado",             "m2",    11.40, "Levantado de solado existente (gres / baldosa hidráulica), preparación de soporte"),
    ("DEM", 5, "levantado_alicatado",          "m2",     9.20, "Levantado de alicatado, incluso preparación de paramento"),
    ("DEM", 6, "desmontaje_carpinteria",       "m2",    12.50, "Desmontaje de carpintería de madera, recuperación de hueco"),
    ("DEM", 7, "picado_enlucido",              "m2",     8.80, "Picado de enlucido o yeso, preparación de paramento para nuevo revestimiento"),
    ("DEM", 8, "apertura_hueco_tabique",       "ud",    88.00, "Apertura de hueco en tabique LH, hasta 1 m², sin refuerzo estructural"),

    # Movimiento de tierras
    ("TER", 1, "excavacion_cielo_abierto",     "m3",    14.20, "Excavación a cielo abierto en terreno medio, medios mecánicos"),
    ("TER", 2, "excavacion_zanjas",            "m3",    24.50, "Excavación de zanjas para cimentación, medios mecánicos"),
    ("TER", 3, "relleno_tierras",              "m3",     7.80, "Relleno con tierras propias compactadas por tongadas"),
    ("TER", 4, "transporte_tierras",           "m3",    12.40, "Transporte de tierras a vertedero autorizado, distancia hasta 20 km"),

    # Cimentación
    ("CIM", 1, "hormigon_limpieza",            "m3",    78.00, "Hormigón de limpieza HL-150/B/20, e=10 cm"),
    ("CIM", 2, "hormigon_zapatas",             "m3",   156.00, "Hormigón armado en zapatas HA-25/B/20/IIa"),
    ("CIM", 3, "acero_corrugado",              "kg",     1.45, "Acero corrugado B500S colocado, incluso despuntes"),
    ("CIM", 4, "hormigon_losa",                "m3",   175.00, "Hormigón armado en losa de cimentación HA-30/B/20/IIa"),
    ("CIM", 5, "encofrado_muros",              "m2",    22.50, "Encofrado plano para muros de cimentación, 2 puestas"),
    ("CIM", 6, "solera_hormigon",              "m2",    42.50, "Solera de hormigón armado HA-25 e=15 cm, mallazo electrosoldado"),

    # Estructura
    ("EST", 1, "hormigon_pilares",             "m3",   245.00, "Hormigón armado en pilares HA-25, incluso encofrado y armaduras"),
    ("EST", 2, "forjado_unidireccional",       "m2",    88.00, "Forjado unidireccional viguetas + bovedilla h=25 cm"),
    ("EST", 3, "losa_maciza",                  "m2",   132.00, "Losa maciza de hormigón armado e=20 cm, HA-25"),
    ("EST", 4, "acero_estructural",            "kg",     2.90, "Acero estructural S275JR en perfiles laminados, colocado"),
    ("EST", 5, "escalera_hormigon",            "m2",   165.00, "Escalera de hormigón armado, encofrada in situ"),
    ("EST", 6, "refuerzo_viga",                "ud",   380.00, "Refuerzo metálico de viga existente, hasta 3 m de luz"),
    ("EST", 7, "viga_hormigon",                "m",     92.50, "Viga de hormigón armado 30×30, HA-25, encofrado y armaduras"),
    ("EST", 8, "tabicado_palomero",            "m2",    36.00, "Tabicado palomero para formación de pendientes en cubierta"),

    # Cubiertas
    ("CUB", 1, "cubierta_plana_no_transitable","m2",    78.00, "Cubierta plana invertida no transitable, acabado de grava"),
    ("CUB", 2, "cubierta_plana_transitable",   "m2",   110.00, "Cubierta plana transitable con pavimento de gres antideslizante"),
    ("CUB", 3, "cubierta_teja_arabe",          "m2",    95.00, "Cubierta inclinada de teja árabe sobre tablero hidrófugo"),
    ("CUB", 4, "impermeabilizacion_epdm",      "m2",    22.50, "Impermeabilización con lámina EPDM e=1.2 mm, soldada"),
    ("CUB", 5, "canalon_aluminio",             "m",     24.80, "Canalón visto de aluminio lacado, sección 125 mm"),
    ("CUB", 6, "bajante_pvc",                  "m",     18.40, "Bajante PVC Ø110 mm, fijaciones incluidas"),

    # Albañilería
    ("ALB", 1, "tabique_lh7",                  "m2",    22.50, "Tabique de ladrillo hueco del 7 (LH7), recibido con mortero 1:6"),
    ("ALB", 2, "tabique_lh9",                  "m2",    26.80, "Tabique de ladrillo hueco del 9 (LH9), recibido con mortero 1:6"),
    ("ALB", 3, "tabique_pyl",                  "m2",    38.50, "Tabique de placa de yeso laminado, doble placa 15+15 mm con lana mineral"),
    ("ALB", 4, "trasdosado_pyl",               "m2",    42.00, "Trasdosado autoportante PYL 15 mm + perfilería + lana mineral 50 mm"),
    ("ALB", 5, "cerramiento_fabrica_doble",    "m2",    56.50, "Cerramiento de fábrica de doble hoja con cámara de aire"),
    ("ALB", 6, "cerramiento_bloque",           "m2",    38.00, "Cerramiento de bloque de hormigón 20×20×40, recibido con mortero"),
    ("ALB", 7, "recibido_carpinteria",         "m",      8.50, "Recibido de carpintería en hueco de fábrica, mortero de agarre"),
    ("ALB", 8, "apertura_dintel",              "ud",    95.00, "Apertura de hueco con formación de dintel en fábrica existente"),
    ("ALB", 9, "tabicon_ceramico",             "m2",    28.50, "Tabicón de ladrillo cerámico 11×11×25 cm"),
    ("ALB",10, "albardilla_hormigon",          "m",     22.00, "Albardilla de hormigón prefabricado, ancho 25 cm"),

    # Aislamientos
    ("AIS", 1, "aislamiento_xps",              "m2",    12.80, "Aislamiento térmico XPS e=4 cm, encolado en trasdosados"),
    ("AIS", 2, "aislamiento_lana_mineral",     "m2",     9.40, "Aislamiento de lana mineral 50 mm en cámaras de aire"),
    ("AIS", 3, "aislamiento_pur_proyectado",   "m2",    18.50, "Aislamiento de poliuretano proyectado e=3 cm en cubiertas"),
    ("AIS", 4, "impermeabilizacion_sbs",       "m2",    18.00, "Impermeabilización con láminas asfálticas SBS, doble capa"),
    ("AIS", 5, "membrana_poliuretano",         "m2",    21.50, "Membrana impermeabilizante de poliuretano líquido bicomponente"),

    # Revestimientos
    ("REV", 1, "enlucido_yeso",                "m2",     9.00, "Enlucido de yeso a buena vista, 1.5 cm de espesor"),
    ("REV", 2, "guarnecido_enlucido",          "m2",    11.20, "Guarnecido y enlucido de yeso a buena vista"),
    ("REV", 3, "mortero_monocapa",             "m2",    26.50, "Mortero monocapa proyectado en fachada, acabado raspado"),
    ("REV", 4, "estuco_veneciano",             "m2",    38.00, "Estuco veneciano interior, dos manos pulidas"),
    ("REV", 5, "alicatado_azulejo",            "m2",    28.50, "Alicatado de azulejo 20×20 con mortero cola"),
    ("REV", 6, "alicatado_porcelanico",        "m2",    36.50, "Alicatado de gres porcelánico 60×30 rectificado"),
    ("REV", 7, "rodapie_madera",               "m",      7.80, "Rodapié de DM lacado h=7 cm"),
    ("REV", 8, "rodapie_porcelanico",          "m",      8.20, "Rodapié de gres porcelánico h=8 cm"),
    ("REV", 9, "falso_techo_continuo",         "m2",    32.50, "Falso techo PYL continuo con perfilería oculta"),
    ("REV",10, "falso_techo_registrable",      "m2",    24.80, "Falso techo registrable 60×60 sobre perfilería vista"),

    # Pavimentos
    ("PAV", 1, "solado_porcelanico_60",        "m2",    43.20, "Solado de gres porcelánico 60×60 sobre recrecido nivelado"),
    ("PAV", 2, "solado_porcelanico_80",        "m2",    56.80, "Solado de gres porcelánico 80×80 rectificado, junta mínima"),
    ("PAV", 3, "tarima_laminada",              "m2",    28.50, "Solado de tarima flotante laminada AC4, base aislante"),
    ("PAV", 4, "tarima_maciza_roble",          "m2",    88.00, "Tarima maciza de roble e=22 mm, encolada y barnizada"),
    ("PAV", 5, "microcemento",                 "m2",    76.00, "Solado de microcemento bicapa con sellado"),
    ("PAV", 6, "mortero_autonivelante",        "m2",    12.50, "Mortero autonivelante e=5 mm de preparación de soporte"),
    ("PAV", 7, "recrecido_mortero",            "m2",    18.50, "Recrecido de mortero e=5 cm para nivelación"),
    ("PAV", 8, "baldosa_hidraulica",           "m2",    78.00, "Solado de baldosa hidráulica reproducción 20×20"),

    # Carpintería interior
    ("CRI", 1, "puerta_interior_lacada",       "ud",   285.00, "Puerta interior lisa LH82 lacada, premarco y herrajes"),
    ("CRI", 2, "puerta_corredera_empotrada",   "ud",   425.00, "Puerta corredera empotrada LH82, kit completo de estructura y guías"),
    ("CRI", 3, "puerta_doble_vidriera",        "ud",   580.00, "Puerta doble vidriera LH82 con vidrio templado V40"),
    ("CRI", 4, "armario_empotrado",            "ud",   980.00, "Armario empotrado 1.20×2.40, frente lacado, interior melamina"),
    ("CRI", 5, "frontal_armario_corredero",    "ud",   720.00, "Frontal de armario corredero 2.40×2.40, perfilería aluminio"),
    ("CRI", 6, "encimera_cocina_madera",       "m",    220.00, "Encimera de cocina en madera maciza e=30 mm, tratada"),

    # Carpintería exterior
    ("CRE", 1, "ventana_aluminio_rpt",         "m2",   285.00, "Ventana de aluminio RPT con doble acristalamiento 4+12+4"),
    ("CRE", 2, "ventana_pvc",                  "m2",   320.00, "Ventana de PVC 70 mm con doble acristalamiento bajo emisivo"),
    ("CRE", 3, "ventana_corredera_aluminio",   "m2",   340.00, "Ventana corredera de aluminio con vidrio templado de seguridad"),
    ("CRE", 4, "puerta_entrada_acorazada",     "ud",   980.00, "Puerta de entrada acorazada blindada nivel 4"),
    ("CRE", 5, "persiana_pvc",                 "m2",    78.00, "Persiana enrollable de PVC con cajón compacto"),
    ("CRE", 6, "mosquitera_aluminio",          "m2",    36.00, "Mosquitera enrollable de aluminio"),

    # Pintura
    ("PIN", 1, "pintura_plastica_lisa",        "m2",     6.80, "Pintura plástica lisa, dos manos sobre paramento liso"),
    ("PIN", 2, "pintura_plastica_satinada",    "m2",     8.50, "Pintura plástica satinada lavable, dos manos"),
    ("PIN", 3, "pintura_silicato_fachada",     "m2",    14.80, "Pintura al silicato sobre fachada, dos manos"),
    ("PIN", 4, "esmalte_sintetico",            "m2",    12.50, "Esmalte sintético sobre madera o metal, dos manos"),
    ("PIN", 5, "barniz_carpinteria",           "m2",     9.80, "Barniz al agua sobre carpintería interior, dos manos"),

    # Fontanería
    ("FON", 1, "punto_lavabo",                 "ud",   145.00, "Punto de fontanería ACS + AFCH para lavabo, completo"),
    ("FON", 2, "punto_ducha",                  "ud",   165.00, "Punto de fontanería ACS + AFCH para ducha, completo"),
    ("FON", 3, "punto_inodoro",                "ud",   110.00, "Punto de fontanería para inodoro con llave de paso"),
    ("FON", 4, "punto_cocina",                 "ud",   180.00, "Punto de fontanería ACS + AFCH para cocina con lavavajillas"),
    ("FON", 5, "lavabo_porcelana",             "ud",   220.00, "Lavabo de porcelana mural con grifería monomando"),
    ("FON", 6, "inodoro_porcelana",            "ud",   245.00, "Inodoro de porcelana con cisterna baja, doble descarga"),
    ("FON", 7, "plato_ducha",                  "ud",   380.00, "Plato de ducha 100×70 + grifería termostática + mampara"),

    # Saneamiento
    ("SAN", 1, "saneamiento_horizontal_110",   "m",     36.50, "Red horizontal de saneamiento PVC Ø110, colgada de forjado"),
    ("SAN", 2, "saneamiento_vertical_110",     "m",     28.50, "Red vertical de saneamiento PVC Ø110, abrazaderas isofónicas"),
    ("SAN", 3, "arqueta_paso",                 "ud",   145.00, "Arqueta de paso 40×40 de hormigón prefabricado"),
    ("SAN", 4, "sumidero_terraza",             "ud",    78.00, "Sumidero sifónico de acero inoxidable para terraza"),
    ("SAN", 5, "bote_sifonico",                "ud",    22.50, "Bote sifónico PVC Ø110 para registro"),

    # Electricidad
    ("ELE", 1, "punto_luz_simple",             "ud",    78.00, "Punto de luz simple, mecanismo de calidad media"),
    ("ELE", 2, "punto_luz_conmutado",          "ud",   110.00, "Punto de luz conmutado entre dos puntos"),
    ("ELE", 3, "punto_enchufe_16a",            "ud",    56.00, "Punto de enchufe 16 A, mecanismo de calidad media"),
    ("ELE", 4, "punto_enchufe_25a",            "ud",    88.00, "Punto de enchufe 25 A para cocina u horno"),
    ("ELE", 5, "cuadro_general",               "ud",   320.00, "Cuadro general de protección con 12 elementos modulares"),
    ("ELE", 6, "punto_tv_datos",               "ud",    92.00, "Punto de TV / datos RJ45, mecanismo y cableado"),
    ("ELE", 7, "canalizacion_corrugado",       "m",      4.80, "Canalización de tubo corrugado PVC Ø20 mm empotrado"),

    # Climatización
    ("CLI", 1, "split_inverter_2500",          "ud",  1450.00, "Split inverter 2.500 frig, gas R-32, instalado"),
    ("CLI", 2, "split_inverter_4500",          "ud",  1850.00, "Split inverter 4.500 frig, gas R-32, instalado"),
    ("CLI", 3, "aerotermia_bibloque",          "ud",  8500.00, "Aerotermia bi-bloque 8 kW para ACS y calefacción, instalada"),
    ("CLI", 4, "suelo_radiante",               "m2",    78.00, "Suelo radiante hidráulico, panel + tubería + colectores"),
    ("CLI", 5, "extraccion_bano",              "ud",   145.00, "Extractor centrífugo para baño, conducto incluido"),

    # Urbanización
    ("URB", 1, "pavimento_hormigon_fratasado", "m2",    38.50, "Pavimento de hormigón fratasado e=15 cm"),
    ("URB", 2, "bordillo_hormigon",            "m",     14.50, "Bordillo de hormigón prefabricado 12×25 cm"),
    ("URB", 3, "pavimento_adoquin",            "m2",    56.00, "Pavimento de adoquín de hormigón 10×20×8 cm"),
    ("URB", 4, "cesped_artificial",            "m2",    24.80, "Césped artificial de 30 mm, sobre base de arena"),
    ("URB", 5, "plantacion_arbusto",           "ud",    18.50, "Plantación de arbusto mediterráneo, contenedor C5"),
]


# Per-partida material lines for the procurement plan. Optional — only filled
# for items where the material is meaningful to track separately.
MATERIALS: list[tuple[str, str, str, float, str, float]] = [
    # (material_code, descripcion, unidad, cantidad_por_partida, partida_code, merma_pct)
    ("MAT-LH7",        "Ladrillo hueco del 7 (24×11.5×7 cm)",      "ud", 40,   "PA-ALB-001", 0.05),
    ("MAT-LH9",        "Ladrillo hueco del 9 (24×11.5×9 cm)",      "ud", 32,   "PA-ALB-002", 0.05),
    ("MAT-PYL15",      "Placa de yeso laminado 15 mm 1.20×2.50",   "m2", 2.0,  "PA-ALB-003", 0.08),
    ("MAT-YESO",       "Yeso negro de obra YG saco 25 kg",         "kg", 11,   "PA-REV-001", 0.05),
    ("MAT-YESO-FINO",  "Yeso fino blanco saco 25 kg",              "kg", 4,    "PA-REV-002", 0.05),
    ("MAT-MORT-COLA",  "Mortero cola para gres porcelánico",       "kg", 5,    "PA-PAV-001", 0.08),
    ("MAT-MORT-COLA",  "Mortero cola para gres porcelánico",       "kg", 5,    "PA-PAV-002", 0.08),
    ("MAT-PORC60",     "Baldosa gres porcelánico 60×60 cm, clase 4","m2", 1.0,  "PA-PAV-001", 0.07),
    ("MAT-PORC80",     "Baldosa gres porcelánico 80×80 cm, rectif.","m2", 1.0,  "PA-PAV-002", 0.08),
    ("MAT-AZULEJO",    "Azulejo cerámico 20×20 cm",                "m2", 1.0,  "PA-REV-005", 0.07),
    ("MAT-PORC60REV",  "Baldosa porcelánica 60×30 rectificada",    "m2", 1.0,  "PA-REV-006", 0.07),
    ("MAT-PIN-PLAST",  "Pintura plástica blanca interior, ~0.2 kg/m²","kg", 0.4, "PA-PIN-001", 0.05),
    ("MAT-PIN-SAT",    "Pintura plástica satinada lavable",        "kg", 0.4,  "PA-PIN-002", 0.05),
    ("MAT-HORMIGON25", "Hormigón HA-25/B/20/IIa central",          "m3", 1.0,  "PA-CIM-002", 0.05),
    ("MAT-HORMIGON25", "Hormigón HA-25/B/20/IIa central",          "m3", 1.0,  "PA-CIM-006", 0.03),
    ("MAT-MALLAZO",    "Mallazo electrosoldado 15×15×6",           "m2", 1.05, "PA-CIM-006", 0.05),
    ("MAT-ACERO-B500", "Acero corrugado B500S",                    "kg", 1.0,  "PA-CIM-003", 0.03),
    ("MAT-TARIMA-LAM", "Tarima flotante laminada AC4",             "m2", 1.0,  "PA-PAV-003", 0.06),
    ("MAT-ROBLE-22",   "Tarima maciza roble 22 mm",                "m2", 1.0,  "PA-PAV-004", 0.08),
    ("MAT-PUERTA-INT", "Puerta interior lisa lacada (juego completo)","ud", 1.0,"PA-CRI-001", 0.00),
    ("MAT-LAVABO",     "Lavabo porcelana mural",                   "ud", 1.0,  "PA-FON-005", 0.00),
    ("MAT-INODORO",    "Inodoro porcelana cisterna baja",          "ud", 1.0,  "PA-FON-006", 0.00),
    ("MAT-PLATO-DUCHA","Plato de ducha 100×70 + grifería",         "ud", 1.0,  "PA-FON-007", 0.00),
    ("MAT-SPLIT-2500", "Split inverter 2.500 frig",                "ud", 1.0,  "PA-CLI-001", 0.00),
]


def code_for(chap_code: str, n: int) -> str:
    return f"PA-{chap_code}-{n:03d}"


def write_catalogue() -> None:
    rows = []
    for chap_code, n, _concept, unidad, total, desc in PARTIDAS:
        chap_name, mo_p, mat_p, maq_p, indir = CHAPTER_RATIOS[chap_code]
        # Split the (pre-indirectos) base into mo / mat / maq so the
        # post-indirectos total matches the supplied figure.
        base = round(total / (1 + indir), 2)
        mo  = round(base * mo_p,  2)
        mat = round(base * mat_p, 2)
        maq = round(base * maq_p, 2)
        # rounding drift correction so mo+mat+maq + 6% lands exactly on total
        drift = round(total - round((mo + mat + maq) * (1 + indir), 2), 2)
        mat = round(mat + drift, 2)
        rows.append({
            "code": code_for(chap_code, n),
            "unidad": unidad,
            "descripcion": desc,
            "mo":  f"{mo:.2f}",
            "mat": f"{mat:.2f}",
            "maq": f"{maq:.2f}",
            "indirectos_pct": f"{indir:.2f}",
            "precio_unitario": f"{total:.2f}",
            "ambito": "Ibiza",
            "fuente": "synthetic-demo",
            "fecha": "2026-04-01",
        })
    out = ROOT / "precios" / "precios_ibiza_2026.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} partidas -> {out.relative_to(ROOT)}")


def write_materials() -> None:
    out = ROOT / "precios" / "materiales_unitarios.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["material_code", "descripcion", "unidad",
                    "cantidad_por_partida", "partida_code", "merma_pct"])
        for code, desc, unidad, qty, partida_code, merma in MATERIALS:
            w.writerow([code, desc, unidad, qty, partida_code, merma])
    print(f"Wrote {len(MATERIALS)} material lines -> {out.relative_to(ROOT)}")


def write_metadata() -> None:
    """JSON output consumed by the engine loader to know which capítulo and
    which price code each scope-item concept resolves to."""
    meta: dict[str, dict] = {}
    for chap_code, n, concept, unidad, _total, desc in PARTIDAS:
        chap_name, *_ = CHAPTER_RATIOS[chap_code]
        meta[concept] = {
            "capitulo": chap_name,
            "price_code": code_for(chap_code, n),
            "unidad": unidad,
            "descripcion_corta": desc.split(",")[0],
        }
    out = ROOT / "_catalogue_seed.json"
    out.write_text(json.dumps({
        "concepto_metadata": meta,
        "capitulo_orden": CHAPTER_ORDER,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(meta)} concepto entries -> {out.relative_to(ROOT)}")


def patch_rules_json() -> None:
    """Merge concepto_metadata + capitulo_orden into rules.json so the
    runner only needs to read rules.json. Preserves all other fields."""
    rules_path = ROOT / "rules.json"
    spec = json.loads(rules_path.read_text(encoding="utf-8"))
    meta: dict[str, dict] = {}
    for chap_code, n, concept, unidad, _total, desc in PARTIDAS:
        chap_name, *_ = CHAPTER_RATIOS[chap_code]
        meta[concept] = {
            "capitulo": chap_name,
            "price_code": code_for(chap_code, n),
            "unidad": unidad,
            "descripcion_corta": desc.split(",")[0],
        }
    spec["concepto_metadata"] = meta
    spec["capitulo_orden"] = CHAPTER_ORDER
    # default plan-de-obra durations for new chapters; preserve any overrides
    cur_durations = spec.get("duracion_capitulo_dias", {})
    default_durations = {
        "Demoliciones": 3, "Movimiento de tierras": 4, "Cimentación": 6,
        "Estructura": 10, "Cubiertas": 7, "Albañilería": 7,
        "Aislamientos e impermeabilizaciones": 4, "Revestimientos": 5,
        "Pavimentos": 4, "Carpintería interior": 3, "Carpintería exterior": 3,
        "Pintura": 5, "Fontanería": 5, "Saneamiento": 4,
        "Electricidad": 5, "Climatización": 3, "Urbanización y exteriores": 5,
    }
    merged = {"_doc": cur_durations.get("_doc", "Reference durations (days)")}
    merged.update(default_durations)
    # overrides win
    for k, v in cur_durations.items():
        if k != "_doc" and k in default_durations:
            merged[k] = v
    spec["duracion_capitulo_dias"] = merged
    # The old per-tipo MAP_ rules are obsolete now that mapping is data-driven.
    spec["rules"] = [r for r in spec.get("rules", [])
                     if not r.get("name", "").startswith("MAP_")
                     and r.get("name") != "PRICE_bind_mejor_precio"]
    # Drop concepto_to_price (subsumed by concepto_metadata)
    spec.pop("concepto_to_price", None)
    rules_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    print(f"Patched -> {rules_path.relative_to(ROOT)} "
          f"({len(meta)} conceptos, {len(spec['rules'])} rules, "
          f"{len(CHAPTER_ORDER)} chapters)")


if __name__ == "__main__":
    write_catalogue()
    write_materials()
    write_metadata()
    patch_rules_json()
