from pathlib import Path
import json,hashlib,subprocess,shutil
setup=Path('/private/tmp/setup_figure13_a4.py').read_text().replace("+'_figure13_a4'","+'_figure13_layout'")
exec(compile(setup,'/private/tmp/setup_figure13_a4.py','exec'))
P=R/'drafts/2026-10-21_20-03-42_figure13_fonts'
manifest=json.loads((B/'manifest.json').read_text())
for p in sorted(x for x in P.rglob('*') if x.is_file()):
    target=B/'original'/p.relative_to(R);target.parent.mkdir(parents=True,exist_ok=True)
    digest=sha(p);subprocess.run(['/bin/cp','-c',str(p),str(target)],check=True)
    assert sha(target)==digest and p.stat().st_ino!=target.stat().st_ino
    manifest.append({'original':str(p),'backup':str(target),'sha256':digest,'bytes':p.stat().st_size})
(B/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
(B/'SHA256SUMS').write_text(''.join(f"{x['sha256']}  original/{Path(x['original']).relative_to(R)}\n" for x in manifest))
for p in [D/'work',D/'tmp/pdfs']:p.mkdir(parents=True,exist_ok=True)
s=json.loads((P/'session.json').read_text());s.update({'draft':str(D),'backup':str(B),'change_log':str(C),'stamp':stamp,
 'previous_draft':str(P),'source_project':str(P/'13_event_validation_fonts.qgz'),
 'source_qpt':str(P/'Figure13_Fonts_For_A4.qpt'),'source_layout':'Figure13_Fonts_For_A4',
 'native_layout':'Figure13_Aligned_Layout','PS_marker_diameter_native_mm':1.1,
 'PS_marker_outline':'none','right_group_gap_native_mm':4.,'font_changes':True,'layout_changes':True,'published':False})
s['font_targets_a4_pt']['classes']=4
for p in [D/'session.json',C/'session.json']:p.write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n')
for name in ['layout_scale_utils.py','compose_and_verify.py','isolation.sb']:shutil.copy2(P/'code'/name,D/'code'/name)
shutil.copy2(P/'source_correspondence.json',D/'source_correspondence.json')
shutil.copy2(__file__,D/'code/setup_layout.py')
report={'files':len(manifest),'bytes':sum(x['bytes'] for x in manifest),'all_hashes_match':True,'independent_inodes':True}
for p in [B/'verification.json',C/'backup_verification.json']:p.write_text(json.dumps(report,indent=2)+'\n')
(B/'README.md').write_text('本次图13布局修改前备份，包含正式图、工程、QPT、引用资源、代码、索引、当前论文和上一版图13全部工作文件。manifest.json列出原路径、SHA-256和字节数，已逐个核验哈希和独立inode。未经用户许可不得删除。\n')
print('LAYOUT_DRAFT='+str(D));print(json.dumps(report))
