#!/usr/bin/env python3
"""Reproduce the north-campus reference SHP from reviewed image ties and vertices.

Run with the seismic Python environment. Existing south-campus and model files
are read-only inputs; the output is a screenshot reference, not an official AOI.
"""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
import zipfile
import cv2
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from affine import Affine
from shapely.geometry import Polygon
from shapely.validation import explain_validity

from qgis_paths import ROOT as BASE
OUT = BASE/'../result/intermediate/campus_digitization/north'
FINAL = BASE/'../data/validation/campuses/yufe_north'
FINAL.mkdir(parents=True,exist_ok=True)
STEM = 'yufe_longquan_north_campus_boundary'


def main():
    meta = json.loads((OUT/'qgis_reference_metadata.json').read_text())
    assert meta['crs'] == 'EPSG:4543' and not meta['errors']
    gcp = pd.read_csv(OUT/'registration_control_points.csv')
    source = np.c_[gcp[['src_x','src_y']].values, np.ones(len(gcp))]
    reference = gcp[['ref_x','ref_y']].values
    assert len(gcp) >= 6 and np.linalg.matrix_rank(source) == 3
    fit = np.linalg.lstsq(source, reference, rcond=None)[0]
    residual = np.linalg.norm(source@fit-reference, axis=1)
    holdout = []
    for i in range(len(gcp)):
        use = np.arange(len(gcp)) != i
        leave_one = np.linalg.lstsq(source[use], reference[use], rcond=None)[0]
        holdout.append(np.linalg.norm(source[i]@leave_one-reference[i]))
    xmin,ymin,xmax,ymax = meta['extent']
    sx = (xmax-xmin)/meta['image_width']
    sy = (ymax-ymin)/meta['image_height']
    assert abs(sx-sy) < 1e-10
    # Image feature coordinates refer to pixel centers; GDAL uses pixel corners.
    world = np.array([[sx,0],[0,-sy],[xmin+.5*sx,ymax-.5*sy]])
    transform = np.column_stack([fit, np.array([0,0,1])])@world
    gcp[['fitted_ref_x','fitted_ref_y']] = source@fit
    gcp[['easting_m','northing_m']] = source@transform
    gcp['residual_m'] = residual*sx
    gcp['leave_one_out_m'] = np.asarray(holdout)*sx
    gcp.to_csv(OUT/'registration_residuals.csv', index=False)
    rmse = float(np.sqrt(np.mean(residual**2))*sx)
    loo = float(np.sqrt(np.mean(np.asarray(holdout)**2))*sx)
    assert rmse < 4 and loo < 5, 'Image ties require review'
    vertices = pd.read_csv(OUT/'boundary_pixel_vertices.csv')
    xy = np.c_[vertices[['pixel_x','pixel_y']].values, np.ones(len(vertices))]
    assert np.array_equal(xy[0], xy[-1]), 'Boundary must be explicitly closed'
    coords = xy@transform
    polygon = Polygon(coords)
    if polygon.is_empty or not polygon.is_valid:
        raise ValueError(explain_validity(polygon))
    assert polygon.exterior.is_closed and len(polygon.interiors) == 0
    vertices[['easting_m','northing_m']] = coords
    vertices.to_csv(OUT/'boundary_projected_vertices.csv', index=False)
    frame = gpd.GeoDataFrame([dict(bnd_id='YUFE_N01',name='云南财经大学龙泉校区北院（截图范围）',
        method='screenshot_trace',source='user_blue_dash',authority='reference_only',
        crs_epsg=4543,area_m2=polygon.area,area_ha=polygon.area/10000,perim_m=polygon.length,
        gcp_n=len(gcp),fit_rmse=rmse,loo_rmse=loo,date='2026-10-13',
        note='用户截图蓝色虚线参考边界；非官方AOI/权籍边界',geometry=polygon)],crs=4543)
    assert all(len(c) <= 10 for c in frame.columns if c != 'geometry')
    frame.to_file(FINAL/(STEM+'.shp'),driver='ESRI Shapefile',encoding='UTF-8')
    reread = gpd.read_file(FINAL/(STEM+'.shp'))
    assert len(reread) == 1 and reread.crs.to_epsg() == 4543
    assert reread.geometry.iloc[0].equals_exact(polygon,1e-8)
    assert reread.iloc[0]['name'] == frame.iloc[0]['name']
    frame.to_crs(4326).to_file(FINAL/(STEM+'_wgs84.geojson'),driver='GeoJSON')
    src = cv2.imread(str(OUT/'input_boundary_screenshot.png'))
    ref = cv2.imread(str(OUT/'qgis_reference_imagery.png'))
    traced = src.copy()
    cv2.polylines(traced,[vertices[['pixel_x','pixel_y']].values.astype('int32')],True,(0,255,255),2,cv2.LINE_AA)
    cv2.imwrite(str(OUT/'01_source_trace_check.png'),traced)
    ref_vertices = xy@fit
    outlined = ref.copy()
    cv2.polylines(outlined,[ref_vertices.astype('int32')],True,(0,255,255),4,cv2.LINE_AA)
    cv2.imwrite(str(OUT/'02_qgis_imagery_boundary_check.png'),outlined)
    warp = cv2.warpAffine(src,fit.T,(meta['image_width'],meta['image_height']))
    mask = cv2.warpAffine(np.ones(src.shape[:2],dtype='uint8'),fit.T,(meta['image_width'],meta['image_height'])) > 0
    blend = ref.copy()
    blend[mask] = cv2.addWeighted(warp,.5,ref,.5,0)[mask]
    cv2.polylines(blend,[ref_vertices.astype('int32')],True,(0,255,255),3,cv2.LINE_AA)
    cv2.imwrite(str(OUT/'03_registration_overlay_check.png'),blend)
    columns = 4
    sheet = np.ones((((len(gcp)+columns-1)//columns)*160,columns*260,3),dtype='uint8')*255
    for idx,row in gcp.iterrows():
        cx,cy = idx%columns*260,idx//columns*160
        for j,(im,x,y) in enumerate([(src,row.src_x,row.src_y),(ref,row.ref_x,row.ref_y)]):
            crop = cv2.resize(cv2.getRectSubPix(im,(70,70),(float(x),float(y))),(120,120))
            cv2.drawMarker(crop,(60,60),(0,255,255),cv2.MARKER_CROSS,13,1)
            sheet[cy+30:cy+150,cx+j*125:cx+j*125+120] = crop
        cv2.putText(sheet,f'GCP {int(row.gcp_id)} source | QGIS',(cx+3,cy+20),cv2.FONT_HERSHEY_SIMPLEX,.45,(0,0,0),1)
    cv2.imwrite(str(OUT/'registration_feature_pairs.png'),sheet)
    corner = np.array([[1,0,0],[0,1,0],[-.5,-.5,1]])@transform
    raster_affine = Affine(corner[0,0],corner[1,0],corner[2,0],corner[0,1],corner[1,1],corner[2,1])
    with rasterio.open(OUT/'source_screenshot_georeferenced.tif','w',driver='GTiff',height=src.shape[0],width=src.shape[1],count=3,dtype='uint8',crs='EPSG:4543',transform=raster_affine,compress='deflate') as dst:
        dst.write(np.moveaxis(cv2.cvtColor(src,cv2.COLOR_BGR2RGB),2,0))
    files = ['input_boundary_screenshot.png','qgis_reference_imagery.png','registration_control_points.csv','boundary_pixel_vertices.csv']
    report = dict(created_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),feature_count=1,
        geometry_type=polygon.geom_type,valid=polygon.is_valid,closed=polygon.exterior.is_closed,
        vertices_including_closure=len(vertices),holes=0,crs='EPSG:4543',
        area_m2=polygon.area,area_ha=polygon.area/10000,perimeter_m=polygon.length,
        gcp_count=len(gcp),fit_rmse_m=rmse,leave_one_out_rmse_m=loo,
        max_leave_one_out_m=float(max(holdout)*sx),reference_pixel_size_m=sx,
        source_to_reference_pixel_affine=fit.T.tolist(),source_pixel_to_epsg4543=transform.T.tolist(),
        internal_registration_error_only=True,absolute_survey_accuracy_verified=False,
        boundary_authority='Screenshot-derived reference; not official AOI or cadastral',
        source_hashes={n:hashlib.sha256((OUT/n).read_bytes()).hexdigest() for n in files},
        shapefile_roundtrip_exact=True)
    (OUT/'digitization_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (OUT/'digitization_run_notes.md').write_text(f'''# 云南财经大学北院截图矢量边界

沿用户2026-10-13提供截图的蓝色虚线绘制1个闭合Polygon，保存为`{STEM}.shp`。仅表示图示龙泉校区北院范围，与此前南侧校园边界分别存储。

坐标系：EPSG:4543，CGCS2000 / 3-degree Gauss-Kruger CM 102E。面积约{polygon.area/10000:.2f}公顷，周长约{polygon.length:.1f}米。

## 配准和描绘

从当前QGIS的Esri World Imagery导出2400×2400参考影像及坐标范围，原截图808×986像素。全图SIFT初配准只有3个一致点且变换明显错误，已弃用。采用人工粗配准限制候选位置，SIFT空间搜索、RANSAC筛选并检查影像点对和整体叠加。排除一个位于北西侧相邻改建地块的模糊特征点（见`rejected_control_points.csv`），接受{len(gcp)}个分散同名特征点，拟合六参数仿射变换。

拟合RMSE约{rmse:.2f}米，留一核查RMSE约{loo:.2f}米，最大约{max(holdout)*sx:.2f}米。这些是内部影像配准误差，不代表独立实测的绝对精度。截图和底图的影像日期、建筑改建、屋顶视差及人工描线影响实际定位；北西侧相邻地块在两幅影像中可见改建变化。

沿虚线取{len(vertices)-1}个顶点并闭合，保留北侧折角、西侧折线和南侧凹口。没有用缓冲区或凸包代替。导出后重新读取，核对中文属性、坐标系、面有效性、闭合性及坐标一致性。

属性`authority=reference_only`：本数据为截图描绘的参考边界，非高德/百度正式AOI、权籍或实测围墙边界。未修改南侧边界或重新计算风险。

## 文件和复现

- `{STEM}.shp`及同名`.shx/.dbf/.prj/.cpg`应一起保留；`{STEM}_shp.zip`包含完整五件套。
- `{STEM}_wgs84.geojson`为EPSG:4326辅助副本。
- `input_boundary_screenshot.png`保留用户原图；`qgis_reference_imagery.png`和`qgis_reference_metadata.json`保存QGIS配准依据。
- `registration_control_points.csv`、`registration_residuals.csv`、`registration_feature_pairs.png`保存最终点对及内部误差。
- `boundary_pixel_vertices.csv`、`boundary_projected_vertices.csv`保存描线顶点。
- `01_source_trace_check.png`、`02_qgis_imagery_boundary_check.png`、`03_registration_overlay_check.png`供描线和定位复核。
- `source_screenshot_georeferenced.tif`为带配准坐标的原截图，仅供核查。
- `digitization_audit.json`保存仿射参数及核验。

复现：`python plot/shared/qgis/scripts/digitize_yufe_north_boundary.py`。
QGIS中执行`shared/qgis/scripts/inspect_yufe_north_reference.py`导出参考影像，执行`shared/qgis/scripts/open_project.py`加载SHP并保存工程。

影像©Esri及其提供者，原截图由用户提供。没有调用API或保存密钥。

![截图描线核对](01_source_trace_check.png)

![QGIS卫星底图核对](02_qgis_imagery_boundary_check.png)
''',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
