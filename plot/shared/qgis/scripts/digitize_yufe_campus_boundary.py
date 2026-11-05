#!/usr/bin/env python3
"""Reproduce the user-image boundary in EPSG:4543 from reviewed image ties.

Read-only on existing model results and project. Run in the seismic environment.
The output is a screenshot-derived reference polygon, never an official AOI.
"""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
import os
import zipfile

os.environ.setdefault('MPLCONFIGDIR','/private/tmp/seismic_building_matplotlib')
import cv2
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from affine import Affine
from shapely.geometry import Polygon
from shapely.validation import explain_validity

from qgis_paths import ROOT as BASE
OUT=BASE/'../result/intermediate/campus_digitization/south'
FINAL=BASE/'../data/validation/campuses/yufe_south'
FINAL.mkdir(parents=True,exist_ok=True)
STEM='yufe_longquan_campus_boundary'


def main():
    meta=json.loads((OUT/'qgis_reference_metadata.json').read_text())
    assert meta['crs']=='EPSG:4543' and not meta['errors']
    gcp=pd.read_csv(OUT/'registration_control_points.csv')
    source=np.c_[gcp[['src_x','src_y']].values,np.ones(len(gcp))]
    reference=gcp[['ref_x','ref_y']].values
    fit=np.linalg.lstsq(source,reference,rcond=None)[0]
    assert np.linalg.matrix_rank(source)==3
    residual=np.linalg.norm(source@fit-reference,axis=1)
    holdout=[]
    for i in range(len(gcp)):
        use=np.arange(len(gcp))!=i
        leave_one=np.linalg.lstsq(source[use],reference[use],rcond=None)[0]
        holdout.append(np.linalg.norm(source[i]@leave_one-reference[i]))
    xmin,ymin,xmax,ymax=meta['extent']
    sx=(xmax-xmin)/meta['image_width'];sy=(ymax-ymin)/meta['image_height']
    assert abs(sx-sy)<1e-10
    world=np.array([[sx,0],[0,-sy],[xmin+.5*sx,ymax-.5*sy]])
    # Build a 3x3 homogeneous transform to preserve subpixel center convention.
    ref_h=np.column_stack([fit,np.array([0,0,1])])
    transform=ref_h@world
    gcp[['fitted_ref_x','fitted_ref_y']]=source@fit
    gcp[['easting_m','northing_m']]=source@transform
    gcp['residual_px']=residual
    gcp['residual_m']=residual*sx
    gcp['leave_one_out_m']=np.asarray(holdout)*sx
    gcp.to_csv(OUT/'registration_residuals.csv',index=False)
    rmse=float(np.sqrt(np.mean(residual**2))*sx)
    loo=float(np.sqrt(np.mean(np.asarray(holdout)**2))*sx)
    assert rmse<4 and loo<5, 'Image ties require review'
    vertices=pd.read_csv(OUT/'boundary_pixel_vertices.csv')
    xy=np.c_[vertices[['pixel_x','pixel_y']].values,np.ones(len(vertices))]
    coords=xy@transform
    polygon=Polygon(coords)
    if polygon.is_empty or not polygon.is_valid:
        raise ValueError(explain_validity(polygon))
    assert polygon.exterior.is_closed and len(polygon.interiors)==0
    vertices[['easting_m','northing_m']]=coords
    vertices.to_csv(OUT/'boundary_projected_vertices.csv',index=False)
    frame=gpd.GeoDataFrame([dict(bnd_id='YUFE_IMG01',name='云南财经大学（龙泉校区截图范围）',
         method='screenshot_trace',source='user_blue_dash',authority='reference_only',
         crs_epsg=4543,area_m2=polygon.area,area_ha=polygon.area/10000,perim_m=polygon.length,
         gcp_n=len(gcp),fit_rmse=rmse,loo_rmse=loo,date='2026-10-12',
         note='用户截图蓝色虚线参考边界；非官方AOI/权籍边界',geometry=polygon)],crs=4543)
    assert all(len(c)<=10 for c in frame.columns if c!='geometry')
    frame.to_file(FINAL/(STEM+'.shp'),driver='ESRI Shapefile',encoding='UTF-8')
    reread=gpd.read_file(FINAL/(STEM+'.shp'))
    assert len(reread)==1 and reread.crs.to_epsg()==4543
    assert reread.geometry.iloc[0].equals_exact(polygon,1e-8)
    frame.to_crs(4326).to_file(FINAL/(STEM+'_wgs84.geojson'),driver='GeoJSON')
    src=cv2.imread(str(OUT/'input_boundary_screenshot.png'))
    ref=cv2.imread(str(OUT/'qgis_reference_imagery.png'))
    traced=src.copy()
    cv2.polylines(traced,[vertices[['pixel_x','pixel_y']].values.astype('int32')],True,(0,255,255),2,cv2.LINE_AA)
    cv2.imwrite(str(OUT/'01_source_trace_check.png'),traced)
    outlined=ref.copy()
    ref_vertices=xy@fit
    cv2.polylines(outlined,[ref_vertices.astype('int32')],True,(0,255,255),4,cv2.LINE_AA)
    cv2.imwrite(str(OUT/'02_qgis_imagery_boundary_check.png'),outlined)
    warp=cv2.warpAffine(src,fit.T,(meta['image_width'],meta['image_height']))
    mask=cv2.warpAffine(np.ones(src.shape[:2],dtype='uint8'),fit.T,(meta['image_width'],meta['image_height']))>0
    blend=ref.copy();blend[mask]=cv2.addWeighted(warp,.50,ref,.50,0)[mask]
    cv2.polylines(blend,[ref_vertices.astype('int32')],True,(0,255,255),3,cv2.LINE_AA)
    cv2.imwrite(str(OUT/'03_registration_overlay_check.png'),blend)
    # Rebuild the reviewed tie-pair image using only accepted control points.
    sheet=np.ones((4*160,4*260,3),dtype='uint8')*255
    for idx,row in gcp.iterrows():
        cx,cy=idx%4*260,idx//4*160
        for j,(image,x,y) in enumerate([(src,row.src_x,row.src_y),(ref,row.ref_x,row.ref_y)]):
            crop=cv2.getRectSubPix(image,(70,70),(float(x),float(y)))
            crop=cv2.resize(crop,(120,120))
            cv2.drawMarker(crop,(60,60),(0,255,255),cv2.MARKER_CROSS,13,1)
            sheet[cy+30:cy+150,cx+j*125:cx+j*125+120]=crop
        cv2.putText(sheet,f'GCP {int(row.gcp_id)} source | QGIS',(cx+3,cy+20),cv2.FONT_HERSHEY_SIMPLEX,.45,(0,0,0),1)
    cv2.imwrite(str(OUT/'registration_feature_pairs.png'),sheet)
    # Optional georeferenced screenshot, stored without altering its pixels.
    corner=np.array([[1,0,0],[0,1,0],[-.5,-.5,1]])@transform
    raster_affine=Affine(corner[0,0],corner[1,0],corner[2,0],corner[0,1],corner[1,1],corner[2,1])
    rgb=cv2.cvtColor(src,cv2.COLOR_BGR2RGB)
    with rasterio.open(OUT/'source_screenshot_georeferenced.tif','w',driver='GTiff',height=src.shape[0],width=src.shape[1],count=3,dtype='uint8',crs='EPSG:4543',transform=raster_affine,compress='deflate') as dst:
        dst.write(np.moveaxis(rgb,2,0))
    checksum={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in [OUT/'input_boundary_screenshot.png',OUT/'qgis_reference_imagery.png',OUT/'registration_control_points.csv',OUT/'boundary_pixel_vertices.csv']}
    report=dict(created_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),feature_count=1,
        geometry_type=polygon.geom_type,valid=polygon.is_valid,closed=polygon.exterior.is_closed,
        vertices_including_closure=len(vertices),holes=0,crs='EPSG:4543',
        area_m2=polygon.area,area_ha=polygon.area/10000,perimeter_m=polygon.length,
        gcp_count=len(gcp),fit_rmse_m=rmse,leave_one_out_rmse_m=loo,
        max_leave_one_out_m=float(max(holdout)*sx),reference_pixel_size_m=sx,
        source_to_reference_pixel_affine=fit.T.tolist(),source_pixel_to_epsg4543=transform.T.tolist(),
        internal_registration_error_only=True,absolute_survey_accuracy_verified=False,
        boundary_authority='Screenshot-derived reference; not official AOI or cadastral',
        source_hashes=checksum,shapefile_roundtrip_exact=True)
    (OUT/'digitization_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (OUT/'digitization_run_notes.md').write_text(f'''# 云南财经大学截图矢量边界

已沿用户2026-10-12提供图片中的蓝色虚线描绘**1个闭合Polygon**，保存为`{STEM}.shp`。范围仅代表截图蓝线，不自动扩展至北院其他范围、安宁校区或龙泉路西侧地块。

坐标系：**EPSG:4543，CGCS2000 / 3-degree Gauss-Kruger CM 102E**，与当前QGIS工程一致。面积约**{polygon.area/10000:.2f}公顷**，周长约{polygon.length:.1f}m。面积描述截图范围，不等于学校官方占地面积。

## 配准与描绘

1. 在打开的QGIS工程中，从Esri World Imagery导出2400×2400参考影像及投影范围，见`qgis_reference_metadata.json`。原始截图1390×1168像素，没有地理坐标。
2. 用校园和周边同名影像特征配准。初始全图SIFT只得到4个一致点且叠加位置错误，已排除；采用人工粗配准约束空间搜索，提取候选并做RANSAC、去重、叠加核对。一个东南侧模糊屋顶点留一残差过大，另存`rejected_control_point.csv`并排除。
3. 最终使用{len(gcp)}个分散同名影像特征拟合6参数仿射变换。拟合RMSE约{rmse:.2f}m，留一核查RMSE约{loo:.2f}m，最大约{max(holdout)*sx:.2f}m。这些是影像配准内部误差，不能代表独立测量的地面精度；影像日期、屋顶视差、截图模糊和人工描线仍有影响。
4. 沿蓝色虚线取{len(vertices)-1}个顶点并闭合，保留北侧折角、沿江弯折、盘江花园侧凹口和南侧突出部分。未做缓冲或凸包替代。
5. 导出后重新读取SHP，核对坐标系、中文编码、面有效性和坐标一致性，均通过。没有重算风险或更改验证筛选区域。

**属性已注明`authority=reference_only`：这是依据用户截图绘制的参考边界，不是高德/百度正式AOI，不是权籍或实测围墙边界。**

## 文件

- `{STEM}.shp`与同名`.shx/.dbf/.prj/.cpg`：完整Shapefile，请一起保留。
- `{STEM}_shp.zip`：5个SHP配套文件的打包。
- `{STEM}_wgs84.geojson`：转换到EPSG:4326的辅助副本。
- `input_boundary_screenshot.png`：用户原图副本。
- `01_source_trace_check.png`：黄色线与用户蓝线的描绘核对。
- `02_qgis_imagery_boundary_check.png`、`03_registration_overlay_check.png`：QGIS卫星底图上的定位和配准核对。
- `registration_control_points.csv`、`registration_residuals.csv`、`registration_feature_pairs.png`：接受的同名影像点、误差和点对。
- `boundary_pixel_vertices.csv`、`boundary_projected_vertices.csv`：像素与投影坐标顶点。
- `source_screenshot_georeferenced.tif`：按拟合变换赋坐标的截图，仅供核对。
- `digitization_audit.json`：复算参数和校验。

复现代码：`plot/shared/qgis/scripts/digitize_yufe_campus_boundary.py`；QGIS加载代码：`plot/shared/qgis/scripts/open_project.py`。

参考影像©Esri及其影像提供者；原图由用户提供，来源界面标注按原样保留。本次没有调用AOI权限接口或写入API密钥。

![原图描线](01_source_trace_check.png)

![QGIS底图核对](02_qgis_imagery_boundary_check.png)
''',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
