"""Repaint saved PS diagnostics with the requested A4 point size only."""
from pathlib import Path
import json,importlib.util,re
D=Path(__file__).resolve().parents[1];S=json.loads((D/'session.json').read_text())
R=Path(S['root']);B=Path(S['backup'])

def main():
    text=(R/'plot/12_insar_contribution/code/render_latest_case_strip.py').read_text()
    replacements={
        'BASE = Path(__file__).resolve().parents[3]':'BASE = Path('+repr(str(R))+')',
        "OUT = BASE / 'plot/12_insar_contribution/output/support'":"OUT = Path("+repr(str(D/'work'))+")",
        "SOURCE = BASE / 'result/discussion/12_insar_contribution/static_baseline'":"SOURCE = Path("+repr(str(R/'result/discussion/12_insar_contribution/static_baseline'))+")",
        "'font.size': 8":"'font.size': FONT_PT",
        'fontsize=8.8 if row == 0 else 7.5':'fontsize=FONT_PT',
        'fontsize=7.5':'fontsize=FONT_PT','fontsize=8.0':'fontsize=FONT_PT',
        'labelsize=7.5':'labelsize=FONT_PT',
        '    fig.savefig(svg, dpi=600)':'''    # Keep halo paths, then add the identical normal text as an embedded-font
    # artist. This retains the visible halo and makes all PDF text measurable.
    from matplotlib.text import Text
    import copy
    outlined=set()
    for original in list(fig.findobj(Text)):
        if not original.get_visible() or not original.get_text() or not original.get_path_effects():continue
        effects=original.get_path_effects()
        original.set_path_effects([pe.Stroke(**e._gc) for e in effects])
        normal=copy.copy(original);normal.set_path_effects([]);normal.set_zorder(original.get_zorder()+.001)
        original.axes.add_artist(normal);outlined.add(id(original))
    fig.canvas.draw()
    inventory=[]
    for t in fig.findobj(Text):
        if not t.get_visible() or not t.get_text() or id(t) in outlined:continue
        assert abs(t.get_fontsize()-FONT_PT)<1e-10
        inventory.append({'text':t.get_text(),'native_pt':t.get_fontsize(),'family':t.get_fontfamily(),
            'weight':t.get_fontweight(),'target_a4_pt':5.5})
    (OUT/'strip_text_inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\\n')
    fig.savefig(OUT/'latest_case_strip.pdf',dpi=600)
    fig.savefig(svg, dpi=600)'''
    }
    for old,new in replacements.items():
        text,n=re.subn(re.escape(old)+r'(?![\d.])',lambda m:new,text)
        assert n>0,old
    # The native SVG is stretched into the existing QGIS picture frame.
    font=5.5*json.loads((D/'paper_scale.json').read_text())['K']/(S['font_scale_y']*82.0774/82.07736944444444)
    text=text.replace('from pathlib import Path','from pathlib import Path\nFONT_PT = '+repr(font),1)
    source=D/'source/render_latest_case_strip.py';source.write_text(text)
    spec=importlib.util.spec_from_file_location('figure12_strip_draft',source);m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m);m.main()
    old=json.loads((R/'plot/12_insar_contribution/output/support/case_strip_manifest.json').read_text())
    new=json.loads((D/'work/case_strip_manifest.json').read_text())
    for key in ['width_mm','height_mm','axes','PS_checks','building_ids','rate_bounds','residual_bounds','window_m','display_extent_m']:
        assert new[key]==old[key],key
    (D/'strip_report.json').write_text(json.dumps({'pdf':str(D/'work/latest_case_strip.pdf'),
        'svg':str(D/'work/latest_case_strip.svg'),'native_pt':font,'target_a4_pt':5.5,
        'native_size_mm':[new['width_mm'],new['height_mm']],
        'PS_coordinates_and_case_metrics_preserved':True,'axes_color_scales_data_windows_preserved':True,
        'PS_counts':[109,57],'black_rings':[11,6],'data_recomputed':True},ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':main()
