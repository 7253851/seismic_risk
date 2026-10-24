"""Uniform font enlargement so that figures print at their A4 point sizes.

A figure exported W mm wide and placed in the paper P mm wide prints its text at
P/W of the A4 size. Multiplying every font by K = W/P restores the A4 sizes.
Geometry, symbols and data are untouched; only text sizes change.
"""
import json
from pathlib import Path

PAPER_FULL_WIDTH_PT = 466.58284759521484  # measured printed width of a 1.00\textwidth figure
PAPER_FULL_WIDTH_MM = PAPER_FULL_WIDTH_PT/72*25.4


def factor(figure_width_px, width_fraction=1.0, dpi=600):
    return (figure_width_px/dpi*25.4)/(PAPER_FULL_WIDTH_MM*width_fraction)


def load(folder):
    path = Path(folder)/'paper_scale.json'
    return json.loads(path.read_text()) if path.exists() else {'K': 1.0}


def scale_mpl(fig, k):
    """Scale every matplotlib text, including tick labels and legends."""
    from matplotlib.text import Text
    fig.canvas.draw()
    for ax in fig.axes:
        for axis, name in [(ax.xaxis, 'x'), (ax.yaxis, 'y')]:
            labels = [t for t in axis.get_ticklabels() if t.get_text()]
            for which in ('major', 'minor'):
                ticks = axis.get_major_ticks() if which == 'major' else axis.get_minor_ticks()
                if ticks:
                    size = ticks[0].label1.get_fontsize()
                    ax.tick_params(axis=name, which=which, labelsize=size*k)
    seen = set()
    for text in fig.findobj(Text):
        if id(text) in seen:
            continue
        seen.add(id(text))
        parent = getattr(text, 'axes', None)
        if parent is not None and (text in parent.xaxis.get_ticklabels(which='both')
                                   or text in parent.yaxis.get_ticklabels(which='both')):
            continue
        text.set_fontsize(text.get_fontsize()*k)
    return len(seen)


def _scale_format(fmt, k):
    fmt.setSize(fmt.size()*k)
    buffer = fmt.buffer()
    if buffer.enabled():
        buffer.setSize(buffer.size()*k)
        fmt.setBuffer(buffer)
    return fmt


def scale_layout(layout, k):
    """Scale text of labels, legends, scale bars, map grids and layer labeling."""
    from qgis.core import (QgsLayoutItemLabel, QgsLayoutItemLegend, QgsLayoutItemMap,
                           QgsLayoutItemScaleBar, QgsLegendStyle, QgsVectorLayer,
                           QgsVectorLayerSimpleLabeling, QgsRuleBasedLabeling)
    counts = {'labels': 0, 'legends': 0, 'scalebars': 0, 'grids': 0, 'layer_labeling': 0}
    layers = {}
    for item in layout.items():
        if isinstance(item, QgsLayoutItemLabel):
            item.setTextFormat(_scale_format(item.textFormat(), k)); counts['labels'] += 1
        elif isinstance(item, QgsLayoutItemLegend):
            for role in (QgsLegendStyle.Title, QgsLegendStyle.Group, QgsLegendStyle.Subgroup, QgsLegendStyle.SymbolLabel):
                style = item.style(role)
                style.setTextFormat(_scale_format(style.textFormat(), k))
                item.setStyle(role, style)
            counts['legends'] += 1
        elif isinstance(item, QgsLayoutItemScaleBar):
            item.setTextFormat(_scale_format(item.textFormat(), k)); counts['scalebars'] += 1
        elif isinstance(item, QgsLayoutItemMap):
            for grid in item.grids().asList():
                grid.setAnnotationTextFormat(_scale_format(grid.annotationTextFormat(), k)); counts['grids'] += 1
            for layer in item.layers():
                layers[layer.id()] = layer
    for layer in layers.values():
        if not isinstance(layer, QgsVectorLayer) or not layer.labelsEnabled() or layer.labeling() is None:
            continue
        labeling = layer.labeling().clone()
        if isinstance(labeling, QgsVectorLayerSimpleLabeling):
            settings = labeling.settings(); settings.setFormat(_scale_format(settings.format(), k))
            labeling.setSettings(settings)
        elif isinstance(labeling, QgsRuleBasedLabeling):
            for rule in labeling.rootRule().descendants():
                if rule.settings():
                    settings = rule.settings(); settings.setFormat(_scale_format(settings.format(), k))
                    rule.setSettings(settings)
        layer.setLabeling(labeling); counts['layer_labeling'] += 1
    layout.refresh()
    return counts
