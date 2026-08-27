"""Sunum slaytları için tema-sadık SVG görselleri.

Bu modül veri çekmez; yalnızca `ecommerce_mcp.PRESENTATION_STYLE` paletini alıp
ondan SVG üretir. Amaç, modern sunum araçlarındaki (Gamma, Pitch, Gemma benzeri)
görselleştirmeleri sabit tema içinde vermek: renk ve yazı tipi seçimi çağırana
bırakılmaz, hepsi paletten gelir.

Üretilen SVG'ler kendi kendine yeter (harici font/asset yok) ve hem HTML
sunumlara hem de PowerPoint'e görsel olarak gömülebilir.
"""

from __future__ import annotations

from html import escape
from typing import Any

# 16:9 slayt içeriği için varsayılan tuval.
WIDTH = 1280
HEIGHT = 640


def _fonts(theme: dict) -> tuple[str, str]:
    """Başlık ve gövde yazı tiplerini yedekleriyle birlikte döndürür."""
    typography = theme.get("typography", {})
    heading = typography.get("heading_font", "Georgia")
    body = typography.get("body_font", "Calibri")
    return f"{heading}, 'Times New Roman', serif", f"{body}, 'Helvetica Neue', sans-serif"


def _accent_list(theme: dict) -> list[str]:
    """Vurgu renklerini spec'teki sırayla verir."""
    accents = theme.get("accents", {})
    order = ("primary", "teal", "terracotta", "green")
    return [accents[key] for key in order if key in accents] or ["#D97706"]


def _clip(text: Any, limit: int) -> str:
    """Metni kırpar ve XML için kaçışlar."""
    value = "" if text is None else str(text)
    if len(value) > limit:
        value = value[: limit - 1].rstrip() + "…"
    return escape(value)


def _header(theme: dict, title: str, subtitle: str) -> tuple[str, int]:
    """Başlık bloğunu çizer ve içeriğin başlayabileceği y değerini döndürür.

    Alt başlık, başlığa sabit ofsetle değil başlık satır sayısına göre
    konumlandırılır — tasarım sistemindeki metin çakışması kuralı bu.
    """
    heading_font, body_font = _fonts(theme)
    palette = theme["palette"]
    parts = []
    y = 72

    if title:
        parts.append(
            f'<text x="64" y="{y}" font-family="{heading_font}" font-size="38" '
            f'font-weight="700" fill="{palette["text"]}">{_clip(title, 52)}</text>'
        )
        y += 38

    if subtitle:
        parts.append(
            f'<text x="64" y="{y}" font-family="{body_font}" font-size="19" '
            f'fill="{palette["text_muted"]}">{_clip(subtitle, 96)}</text>'
        )
        y += 30

    return "\n".join(parts), y + 34


def _footer(theme: dict, note: str) -> str:
    """Kaynak satırı — tasarım sistemi her slaytta bunu istiyor."""
    if not note:
        return ""
    _, body_font = _fonts(theme)
    return (
        f'<text x="64" y="{HEIGHT - 28}" font-family="{body_font}" font-size="14" '
        f'fill="{theme["palette"]["text_muted"]}">{_clip(note, 130)}</text>'
    )


def _frame(theme: dict, body: str, dark: bool = False) -> str:
    palette = theme["palette"]
    background = palette["surface_dark"] if dark else palette["surface"]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img">\n'
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{background}"/>\n'
        f"{body}\n</svg>"
    )


# --- GÖRSEL TİPLERİ ---


def journey_map(theme: dict, data: dict, title: str, subtitle: str, note: str) -> str:
    """Müşteri yolculuğu haritası: aşamalar, her aşamada ölçü ve not.

    data: {"stages": [{"label": ..., "value": ..., "note": ...}, ...]}
    """
    stages = (data.get("stages") or [])[:6]
    if not stages:
        raise ValueError("journey_map için en az bir 'stages' öğesi gerekli.")

    palette, accents = theme["palette"], _accent_list(theme)
    heading_font, body_font = _fonts(theme)
    header, top = _header(theme, title, subtitle)

    margin = 64
    gap = 22
    usable = WIDTH - 2 * margin
    card_width = (usable - gap * (len(stages) - 1)) / len(stages)
    line_y = top + 34

    # Kart yüksekliği en uzun nota göre belirlenir; sabit yükseklikte kısa
    # notlarda kartın altı boş kalıyordu.
    note_lines = max((len(_wrap(stage.get("note"), 24)[:5]) for stage in stages), default=0)
    card_height = 120 + note_lines * 22

    parts = [header]

    # Aşamaları birbirine bağlayan sürekli çizgi; adımların bir akış olduğunu
    # gösterir, kopuk kutular yığını olmadığını.
    parts.append(
        f'<line x1="{margin + card_width / 2:.0f}" y1="{line_y}" '
        f'x2="{WIDTH - margin - card_width / 2:.0f}" y2="{line_y}" '
        f'stroke="{palette["border_strong"]}" stroke-width="2"/>'
    )

    for index, stage in enumerate(stages):
        x = margin + index * (card_width + gap)
        colour = accents[index % len(accents)]
        centre = x + card_width / 2

        parts.append(
            f'<circle cx="{centre:.0f}" cy="{line_y}" r="15" fill="{colour}"/>'
            f'<circle cx="{centre:.0f}" cy="{line_y}" r="24" fill="none" '
            f'stroke="{colour}" stroke-width="2" opacity="0.28"/>'
            f'<text x="{centre:.0f}" y="{line_y + 6}" font-family="{heading_font}" '
            f'font-size="15" font-weight="700" fill="{palette["surface_card"]}" '
            f'text-anchor="middle">{index + 1}</text>'
        )

        card_top = line_y + 46
        parts.append(
            f'<rect x="{x:.0f}" y="{card_top}" width="{card_width:.0f}" '
            f'height="{card_height}" rx="14" fill="{palette["surface_card"]}" '
            f'stroke="{palette["border"]}"/>'
            f'<rect x="{x:.0f}" y="{card_top}" width="{card_width:.0f}" height="4" '
            f'rx="2" fill="{colour}"/>'
        )

        text_x = x + 22
        parts.append(
            f'<text x="{text_x:.0f}" y="{card_top + 44}" font-family="{heading_font}" '
            f'font-size="19" font-weight="700" fill="{palette["text"]}">'
            f"{_clip(stage.get('label'), 18)}</text>"
        )

        if stage.get("value") is not None:
            parts.append(
                f'<text x="{text_x:.0f}" y="{card_top + 92}" font-family="{heading_font}" '
                f'font-size="32" font-weight="700" fill="{colour}">'
                f"{_clip(stage.get('value'), 12)}</text>"
            )

        for line_index, line in enumerate(_wrap(stage.get("note"), 24)[:5]):
            parts.append(
                f'<text x="{text_x:.0f}" y="{card_top + 128 + line_index * 22}" '
                f'font-family="{body_font}" font-size="15" '
                f'fill="{palette["text_secondary"]}">{escape(line)}</text>'
            )

    parts.append(_footer(theme, note))
    return _frame(theme, "\n".join(parts))


def donut(theme: dict, data: dict, title: str, subtitle: str, note: str) -> str:
    """Tek ölçülü halka göstergesi — çok dilimli pastanın modern karşılığı.

    Birden çok halka verildiğinde yan yana dizilir; her halka TEK bir oranı
    gösterir, böylece dilimleri gözle kıyaslama sorunu doğmaz.

    data: {"rings": [{"label":..., "value": 4.2, "max": 5, "caption":...}, ...]}
    """
    rings = (data.get("rings") or [])[:4]
    if not rings:
        raise ValueError("donut için en az bir 'rings' öğesi gerekli.")

    palette, accents = theme["palette"], _accent_list(theme)
    heading_font, body_font = _fonts(theme)
    header, top = _header(theme, title, subtitle)

    parts = [header]
    slot = (WIDTH - 128) / len(rings)
    radius, stroke = 86, 24
    centre_y = top + 130

    for index, ring in enumerate(rings):
        centre_x = 64 + slot * index + slot / 2
        colour = accents[index % len(accents)]

        try:
            value = float(ring.get("value") or 0)
            maximum = float(ring.get("max") or 100)
        except (TypeError, ValueError):
            value, maximum = 0.0, 100.0
        ratio = 0.0 if maximum <= 0 else max(0.0, min(value / maximum, 1.0))

        circumference = 2 * 3.141592653589793 * radius
        filled = circumference * ratio

        parts.append(
            f'<circle cx="{centre_x:.0f}" cy="{centre_y}" r="{radius}" fill="none" '
            f'stroke="{palette["border"]}" stroke-width="{stroke}"/>'
        )
        if filled > 0:
            parts.append(
                f'<circle cx="{centre_x:.0f}" cy="{centre_y}" r="{radius}" fill="none" '
                f'stroke="{colour}" stroke-width="{stroke}" stroke-linecap="round" '
                f'stroke-dasharray="{filled:.1f} {circumference - filled:.1f}" '
                f'transform="rotate(-90 {centre_x:.0f} {centre_y})"/>'
            )

        display = ring.get("display") or _trim_number(value)
        parts.append(
            f'<text x="{centre_x:.0f}" y="{centre_y + 8}" font-family="{heading_font}" '
            f'font-size="42" font-weight="700" fill="{palette["text"]}" '
            f'text-anchor="middle">{_clip(display, 8)}</text>'
        )
        parts.append(
            f'<text x="{centre_x:.0f}" y="{centre_y + radius + 56}" '
            f'font-family="{heading_font}" font-size="19" font-weight="700" '
            f'fill="{palette["text"]}" text-anchor="middle">'
            f"{_clip(ring.get('label'), 24)}</text>"
        )
        if ring.get("caption"):
            parts.append(
                f'<text x="{centre_x:.0f}" y="{centre_y + radius + 82}" '
                f'font-family="{body_font}" font-size="15" '
                f'fill="{palette["text_muted"]}" text-anchor="middle">'
                f"{_clip(ring.get('caption'), 30)}</text>"
            )

    parts.append(_footer(theme, note))
    return _frame(theme, "\n".join(parts))


def quadrant(theme: dict, data: dict, title: str, subtitle: str, note: str) -> str:
    """Fiyat–puan konumlandırma haritası.

    Kategori analizinde en çok karar verdiren görsel: hangi ürün pahalı ama
    zayıf puanlı, hangisi ucuz ve güçlü — tek bakışta görünür.

    data: {"points":[{"x":1290,"y":4.5,"label":"…","size":29}], "x_label":…, "y_label":…}
    """
    points = [p for p in (data.get("points") or []) if p.get("x") is not None and p.get("y") is not None]
    if not points:
        raise ValueError("quadrant için en az bir 'points' öğesi gerekli.")

    palette, accents = theme["palette"], _accent_list(theme)
    heading_font, body_font = _fonts(theme)
    header, top = _header(theme, title, subtitle)

    left, right = 110, WIDTH - 80
    plot_top, plot_bottom = top + 10, HEIGHT - 96

    xs = [float(p["x"]) for p in points]
    ys = [float(p["y"]) for p in points]
    # Tek noktalı ya da tüm değerleri eşit veri setinde aralık sıfır olur;
    # payda sıfıra düşmesin diye küçük bir tampon eklenir.
    # Fiyat verisi tipik olarak çarpık dağılır (1.290 TL ile 44.500 TL bir arada);
    # doğrusal eksende noktalar sola yığılır. Logaritmik eksen segmentleri ayırır.
    use_log = data.get("x_scale") == "log" and min(xs) > 0
    if use_log:
        from math import log10

        xs = [log10(x) for x in xs]

    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    x_span = (x_max - x_min) or max(abs(x_max), 1.0)
    y_span = (y_max - y_min) or max(abs(y_max), 1.0)
    x_min -= x_span * 0.14
    x_max += x_span * 0.14
    # Üstte ve altta daha geniş pay: nokta etiketleri çeyrek başlıklarına binmesin.
    y_min -= y_span * 0.30
    y_max += y_span * 0.30

    def sx(value: float) -> float:
        if use_log:
            from math import log10

            value = log10(value)
        return left + (value - x_min) / (x_max - x_min) * (right - left)

    def sy(value: float) -> float:
        return plot_bottom - (value - y_min) / (y_max - y_min) * (plot_bottom - plot_top)

    parts = [header]
    mid_x, mid_y = (left + right) / 2, (plot_top + plot_bottom) / 2

    parts.append(
        f'<rect x="{left}" y="{plot_top}" width="{right - left}" '
        f'height="{plot_bottom - plot_top}" fill="{palette["surface_card"]}" '
        f'stroke="{palette["border"]}" rx="12"/>'
        f'<line x1="{mid_x:.0f}" y1="{plot_top}" x2="{mid_x:.0f}" y2="{plot_bottom}" '
        f'stroke="{palette["border"]}" stroke-dasharray="6 6"/>'
        f'<line x1="{left}" y1="{mid_y:.0f}" x2="{right}" y2="{mid_y:.0f}" '
        f'stroke="{palette["border"]}" stroke-dasharray="6 6"/>'
    )

    for label, x_pos, y_pos, anchor in (
        (data.get("q_top_left", "Ucuz · güçlü puan"), left + 16, plot_top + 28, "start"),
        (data.get("q_top_right", "Pahalı · güçlü puan"), right - 16, plot_top + 28, "end"),
        (data.get("q_bottom_left", "Ucuz · zayıf puan"), left + 16, plot_bottom - 16, "start"),
        (data.get("q_bottom_right", "Pahalı · zayıf puan"), right - 16, plot_bottom - 16, "end"),
    ):
        parts.append(
            f'<text x="{x_pos:.0f}" y="{y_pos:.0f}" font-family="{body_font}" '
            f'font-size="14" fill="{palette["text_faint"]}" text-anchor="{anchor}">'
            f"{_clip(label, 26)}</text>"
        )

    for index, point in enumerate(points[:14]):
        cx, cy = sx(float(point["x"])), sy(float(point["y"]))
        colour = accents[index % len(accents)]
        try:
            weight = float(point.get("size") or 0)
        except (TypeError, ValueError):
            weight = 0.0
        radius = 9 + min(weight, 500) / 500 * 13

        parts.append(
            f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{radius:.0f}" fill="{colour}" '
            f'opacity="0.82"/>'
        )
        if point.get("label"):
            anchor = "end" if cx > mid_x else "start"
            offset = -radius - 8 if cx > mid_x else radius + 8
            parts.append(
                f'<text x="{cx + offset:.0f}" y="{cy + 5:.0f}" font-family="{body_font}" '
                f'font-size="14" fill="{palette["text_secondary"]}" '
                f'text-anchor="{anchor}">{_clip(point["label"], 22)}</text>'
            )

    axis_note = " (log ölçek)" if use_log else ""
    parts.append(
        f'<text x="{(left + right) / 2:.0f}" y="{HEIGHT - 58}" font-family="{body_font}" '
        f'font-size="15" fill="{palette["text_muted"]}" text-anchor="middle">'
        f'{_clip(str(data.get("x_label", "Fiyat")) + axis_note, 46)} →</text>'
        f'<text x="34" y="{(plot_top + plot_bottom) / 2:.0f}" font-family="{body_font}" '
        f'font-size="15" fill="{palette["text_muted"]}" text-anchor="middle" '
        f'transform="rotate(-90 34 {(plot_top + plot_bottom) / 2:.0f})">'
        f'{_clip(data.get("y_label", "Puan"), 40)} →</text>'
    )
    parts.append(_footer(theme, note))
    return _frame(theme, "\n".join(parts))


def waffle(theme: dict, data: dict, title: str, subtitle: str, note: str) -> str:
    """100 kareli oran ızgarası — pastanın okunabilir alternatifi.

    Her kare %1'dir; okuyucu dilim açısı tahmin etmek yerine kare sayar.

    data: {"parts": [{"label": "Yorumlu", "value": 5}, ...]}
    """
    segments = [s for s in (data.get("parts") or []) if (s.get("value") or 0) > 0]
    if not segments:
        raise ValueError("waffle için en az bir pozitif 'parts' öğesi gerekli.")

    palette, accents = theme["palette"], _accent_list(theme)
    heading_font, body_font = _fonts(theme)
    header, top = _header(theme, title, subtitle)

    total = sum(float(s["value"]) for s in segments)
    # Kare paylarını dağıtırken toplamın tam 100 olmasını garanti et: yuvarlama
    # artıkları en büyük paya eklenir, ızgarada boşluk kalmaz.
    counts = [int(round(float(s["value"]) / total * 100)) for s in segments]
    drift = 100 - sum(counts)
    if counts:
        counts[counts.index(max(counts))] += drift

    cell, gap = 34, 6
    grid_left, grid_top = 64, top
    parts = [header]

    order = []
    for index, count in enumerate(counts):
        order.extend([index] * max(count, 0))
    order = order[:100]

    for position, segment_index in enumerate(order):
        row, column = divmod(position, 10)
        x = grid_left + column * (cell + gap)
        y = grid_top + row * (cell + gap)
        parts.append(
            f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="7" '
            f'fill="{accents[segment_index % len(accents)]}"/>'
        )

    legend_x = grid_left + 10 * (cell + gap) + 48
    for index, segment in enumerate(segments):
        y = grid_top + 24 + index * 62
        colour = accents[index % len(accents)]
        parts.append(
            f'<rect x="{legend_x}" y="{y - 18}" width="22" height="22" rx="6" fill="{colour}"/>'
            f'<text x="{legend_x + 34}" y="{y}" font-family="{heading_font}" '
            f'font-size="19" font-weight="700" fill="{palette["text"]}">'
            f"{_clip(segment.get('label'), 24)}</text>"
            f'<text x="{legend_x + 34}" y="{y + 24}" font-family="{body_font}" '
            f'font-size="15" fill="{palette["text_muted"]}">'
            f"%{counts[index]} · {_clip(_trim_number(segment['value']), 10)}</text>"
        )

    parts.append(_footer(theme, note))
    return _frame(theme, "\n".join(parts))


def ranked_bars(theme: dict, data: dict, title: str, subtitle: str, note: str) -> str:
    """Büyükten küçüğe sıralı yatay bar — oran karşılaştırmasının varsayılanı.

    data: {"items": [{"label": "…", "value": 2600}], "unit": "TL"}
    """
    items = [i for i in (data.get("items") or []) if i.get("value") is not None]
    if not items:
        raise ValueError("ranked_bars için en az bir 'items' öğesi gerekli.")

    palette = theme["palette"]
    series = theme.get("charts", {}).get("series_color", _accent_list(theme)[0])
    heading_font, body_font = _fonts(theme)
    header, top = _header(theme, title, subtitle)

    items = sorted(items, key=lambda i: float(i["value"]), reverse=True)[:9]
    unit = data.get("unit", "")
    peak = max(float(i["value"]) for i in items) or 1.0

    label_width = 240
    bar_left = 64 + label_width
    bar_max = WIDTH - bar_left - 150
    row_height = min(52, int((HEIGHT - top - 80) / len(items)))

    parts = [header]
    for index, item in enumerate(items):
        y = top + index * row_height
        value = float(item["value"])
        width = max(3.0, value / peak * bar_max)

        parts.append(
            f'<text x="{64 + label_width - 16}" y="{y + row_height / 2 + 6:.0f}" '
            f'font-family="{body_font}" font-size="16" fill="{palette["text_secondary"]}" '
            f'text-anchor="end">{_clip(item.get("label"), 28)}</text>'
            f'<rect x="{bar_left}" y="{y + row_height / 2 - 13:.0f}" width="{width:.0f}" '
            f'height="26" rx="6" fill="{series}"/>'
            f'<text x="{bar_left + width + 14:.0f}" y="{y + row_height / 2 + 6:.0f}" '
            f'font-family="{heading_font}" font-size="17" font-weight="700" '
            f'fill="{palette["text"]}">{_trim_number(value)}{escape(" " + unit if unit else "")}'
            f"</text>"
        )

    parts.append(_footer(theme, note))
    return _frame(theme, "\n".join(parts))


# --- YARDIMCILAR ---


def _trim_number(value: Any) -> str:
    """Sayıyı sunum için okunur biçime getirir (binlik ayıracı nokta)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return escape(str(value))
    if number == int(number):
        return f"{int(number):,}".replace(",", ".")
    return f"{number:,.1f}".replace(",", "~").replace(".", ",").replace("~", ".")


def _wrap(text: Any, width: int) -> list[str]:
    """Basit sözcük sarma — SVG'de otomatik satır kaydırma yok."""
    if not text:
        return []
    lines, current = [], ""
    for word in str(text).split():
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


BUILDERS = {
    "journey_map": journey_map,
    "donut": donut,
    "quadrant": quadrant,
    "waffle": waffle,
    "ranked_bars": ranked_bars,
}


def build(kind: str, theme: dict, data: dict, title: str = "", subtitle: str = "", note: str = "") -> str:
    """İstenen görseli üretir."""
    if kind not in BUILDERS:
        raise ValueError(
            f"Bilinmeyen görsel tipi '{kind}'. Seçenekler: {', '.join(sorted(BUILDERS))}."
        )
    return BUILDERS[kind](theme, data or {}, title, subtitle, note)
