#!/usr/bin/env python3
"""Inspect the exported PDF typography and preservation of the original files."""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import re

import pdfplumber
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[3]
DRAFT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / 'backups/2026-10-21_15-15-56_figure05_fonts'
BASELINE = ROOT / 'drafts/2026-10-21_15-02-53_figure05_a4/figure05_A4.pdf'
PDF = DRAFT / 'figure05_A4.pdf'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def fragments(path):
    result = []
    def collect(text, cm, tm, font, fontsize):
        if text.strip():
            result.append((text.strip(), float(fontsize), str(font.get('/BaseFont'))))
    PdfReader(path).pages[0].extract_text(visitor_text=collect)
    return result


actual = fragments(PDF)
assert all('Arial-BoldMT' in font for _, _, font in actual)
assert not any(text in ('(a)', '(b)', '(c)', '(d)') for text, _, _ in actual)
before_text = re.sub(r'\s+', '', ''.join(text for text, _, _ in fragments(BASELINE)))
for label in ('(a)', '(b)', '(c)', '(d)'):
    before_text = before_text.replace(label, '')
after_text = re.sub(r'\s+', '', ''.join(text for text, _, _ in actual))
assert before_text == after_text, 'Text content/order changed beyond removing panel IDs'

categories = [
    ('四个子图横纵轴标题', 8, lambda t,s: t in ('Building-to-fault horizontal', 'distance (km)', 'Final PGA (g)', 'Vs30 (m/s)', 'PGA (g)', 'Amplification factor, AF')),
    ('四个子图坐标轴刻度', 6, lambda t,s: bool(re.fullmatch(r'[0-9.]+', t)) and s == 6),
    ('色标标题', 7, lambda t,s: t == 'Building count (log scale)'),
    ('色标底数10', 6, lambda t,s: t == '10' and s == 6),
    ('色标上标指数', 4, lambda t,s: s == 4),
    ('断层名称图例', 7, lambda t,s: t == 'Puduhe fault' or t.startswith(('Western branch', 'Xiaojiang fault system', 'segment)'))),
    ('Rrup图例', 7, lambda t,s: t.startswith('Rrup =')),
    ('模型参数说明', 6, lambda t,s: t.startswith(('Mw=', 'Reference Vs30='))),
    ('灰区说明及Vs30范围', 5.5, lambda t,s: t.startswith(('Urban building', 'Vs30:')) or t in ('–', '350 m/s')),
    ('AF = 1标注', 5, lambda t,s: t == 'AF = 1'),
]
rows = []
colorbar_base_indices = {i-1 for i, (_, size, _) in enumerate(actual) if size == 4}
assert len(colorbar_base_indices) == 8
assert all(actual[i][:2] == ('10', 6.0) for i in colorbar_base_indices)
for name, expected, match in categories:
    selected = [(text, size) for i, (text, size, _) in enumerate(actual) if match(text, size)
                and (name != '色标底数10' or i in colorbar_base_indices)
                and (name != '四个子图坐标轴刻度' or i not in colorbar_base_indices)]
    sizes = sorted({size for _, size in selected})
    assert sizes == [expected], (name, sizes, expected)
    rows.append({'元素': name, '目标字号_pt': expected, 'PDF实际字号_pt': sizes[0], '核对文本片段数': len(selected)})
assert Counter(text for text, size, _ in actual if size == 4) == Counter({'0':2, '1':2, '2':2, '3':2})
with (DRAFT / 'actual_font_sizes.csv').open('w', encoding='utf-8-sig', newline='') as stream:
    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)

with pdfplumber.open(PDF) as new, pdfplumber.open(BASELINE) as old:
    page = new.pages[0]
    assert len(new.pages) == 1
    page_mm = [page.width * 25.4/72, page.height * 25.4/72]
    assert abs(page_mm[0] - 210) < 1e-8 and abs(page_mm[1] - 297) < 1e-8
    def axes_boxes(p):
        return [(r['x0'], r['y0'], r['width'], r['height']) for r in p.rects
                if abs(r['width'] - 157.157) < .01 and abs(r['height'] - 126.139) < .01]
    old_boxes, new_boxes = axes_boxes(old.pages[0]), axes_boxes(page)
    assert len(old_boxes) == len(new_boxes) == 4
    panel_error = max(abs(x-y) for a,b in zip(old_boxes,new_boxes) for x,y in zip(a,b))
    assert panel_error < 1e-5
    assert all(c['x0'] >= 0 and c['x1'] <= page.width and c['top'] >= 0 and c['bottom'] <= page.height for c in page.chars)
    # Check PDF text extents, in addition to the Matplotlib reserved text box.
    lower_panel_top = page.height - new_boxes[2][1] - new_boxes[2][3]
    xlabel_words = [w for w in page.extract_words() if w['text'] in ('distance', '(km)') and 210 < w['top'] < 230]
    upper_xlabel_clearance = lower_panel_top - max(w['bottom'] for w in xlabel_words)
    assert upper_xlabel_clearance > 0

manifest = json.loads((BACKUP / 'manifest.json').read_text())
files = [entry for entry in manifest if entry['kind'] == 'file']
backup_errors = [entry['backup'] for entry in files if sha(entry['backup']) != entry['sha256']]
original_changes = [entry['original'] for entry in files if sha(entry['original']) != entry['sha256']]
assert not backup_errors and not original_changes
report = {
    'pdf': str(PDF), 'sha256': sha(PDF), 'page_mm': page_mm,
    'all_requested_font_sizes_verified_from_pdf_text_operators': True,
    'fonts': sorted({font for _,_,font in actual}), 'actual_font_sizes': rows,
    'panel_ids_removed': True, 'remaining_text_content_and_order_unchanged': True,
    'data_panel_bounds_max_error_pt': panel_error,
    'upper_xlabel_to_lower_panel_PDF_text_extent_clearance_pt': upper_xlabel_clearance,
    'all_text_within_A4_page': True,
    'backup_files_verified': len(files), 'backup_errors': backup_errors,
    'original_files_verified_unchanged': len(files), 'original_changes': original_changes,
    'position_adjustments': [{'elements': 'c,d gray notes', 'shift_right_mm': 1.1}],
    'typography_spacing_adjustments': [{'elements': 'a,b two-line x-axis titles',
                                      'linespacing': 1.0, 'anchor_unchanged': True}],
    'unresolved_issues': [],
}
(DRAFT / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False, indent=2))
