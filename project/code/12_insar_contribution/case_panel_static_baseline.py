"""Observed PS, fitted velocity planes and local gradients for composite panel c."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
from scipy.spatial import Delaunay
from shapely import affinity
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.collections import LineCollection
from matplotlib import patheffects as pe

SHORT={'Very Low':'VL','Low':'L','Moderate':'M','High':'H','Very High':'VH'}


def diagnostics(root, data, pair_ids, out):
    where='Build_ID IN ('+','.join(map(str,pair_ids))+')'
    ps=gpd.read_file(root/'result/intermediate/vulnerability_inputs/building_ps_points.gpkg',layer='building_ps_points',where=where)
    buildings=gpd.read_file(root/'result/risk/scs_paper_method/building_risk.gpkg',layer='building_risk_scs',where=where).set_index('Build_ID')
    stored=data.set_index('Build_ID');nodes=[];edges_all=[];details=[]
    for bid in pair_ids:
        group=ps[ps.Build_ID.eq(bid)]
        coordinates=np.c_[group.geometry.x,group.geometry.y]
        xy,inv=np.unique(coordinates,axis=0,return_inverse=True);counts=np.bincount(inv)
        rate=np.bincount(inv,weights=group.v_vertical)/counts
        coherence=np.bincount(inv,weights=group.coh.clip(0,1))/counts
        center=np.average(xy,axis=0,weights=coherence);mean=np.average(rate,weights=coherence)
        z=xy-center
        slopes,*_=np.linalg.lstsq(z*np.sqrt(coherence[:,None]),(rate-mean)*np.sqrt(coherence),rcond=None)
        fitted=mean+z@slopes;residual=rate-fitted
        triangles=Delaunay(xy).simplices
        edges=np.unique(np.sort(np.concatenate([triangles[:,[0,1]],triangles[:,[1,2]],triangles[:,[2,0]]]),axis=1),axis=0)
        left,right=edges.T;distances=np.linalg.norm(xy[left]-xy[right],axis=1)
        valid=(distances>0)&(distances<=20);left,right,distances=left[valid],right[valid],distances[valid]
        edge_gradient=.5*(coherence[left]+coherence[right])*abs(rate[left]-rate[right])/distances
        degree=np.bincount(np.r_[left,right],minlength=len(xy))
        totals=np.bincount(np.r_[left,right],weights=np.r_[edge_gradient,edge_gradient],minlength=len(xy))
        gradient=np.divide(totals,degree,out=np.full(len(xy),np.nan),where=degree>0)
        p90=float(np.nanpercentile(gradient,90));abnormal=gradient>p90
        rms=float(np.sqrt(np.mean(rate**2)))
        tilt=float(np.degrees(np.arctan(np.linalg.norm(slopes)/1000)))
        dgi=float(.5*np.nanmean(gradient[abnormal])+.5*np.nanmax(gradient[abnormal]))
        for name,value in [('V_RMS',rms),('Tilt_Angle',tilt),('DGI_Str',dgi)]:
            assert abs(value-stored.loc[bid,name])<1e-12,(bid,name,value,stored.loc[bid,name])
        assert len(group)==int(stored.loc[bid,'PS_Count'])
        poly=buildings.loc[bid].geometry;origin=np.array([poly.centroid.x,poly.centroid.y])
        local=xy-origin
        assert (abs(local)<=40).all(),'80 m windows must contain all associated PS'
        details.append({'Build_ID':int(bid),'associated_PS_records':len(group),'unique_PS_locations':len(xy),
                        'weighted_center_x':float(center[0]),'weighted_center_y':float(center[1]),
                        'mean_fitted_rate':float(mean),'slope_x':float(slopes[0]),'slope_y':float(slopes[1]),
                        'RMS_rebuilt':rms,'Tilt_rebuilt':tilt,'DGI_rebuilt':dgi,
                        'point_gradient_P90':p90,'gradient_abnormal_n':int(abnormal.sum()),
                        'weighted_residual_RMS':float(np.sqrt(np.average(residual**2,weights=coherence))),
                        'residual_min':float(residual.min()),'residual_max':float(residual.max())})
        for i in range(len(xy)):
            nodes.append({'Build_ID':int(bid),'node':i,'x':float(xy[i,0]),'y':float(xy[i,1]),
                          'observed_rate':float(rate[i]),'fitted_rate':float(fitted[i]),'residual_rate':float(residual[i]),
                          'coherence':float(coherence[i]),'point_gradient':float(gradient[i]),'gradient_abnormal':bool(abnormal[i])})
        for i,j,value in zip(left,right,edge_gradient):
            edges_all.append({'Build_ID':int(bid),'left_node':int(i),'right_node':int(j),'edge_gradient':float(value)})
    nodes=pd.DataFrame(nodes);edges=pd.DataFrame(edges_all)
    nodes.to_csv(out/'data/case_panel_PS_nodes.csv',index=False,float_format='%.17g')
    edges.to_csv(out/'data/case_panel_PS_edges.csv',index=False,float_format='%.17g')
    return buildings,nodes,edges,details


def outline(ax,geometry,center,color,width=1.3,style='-'):
    local=affinity.translate(geometry,xoff=-center[0],yoff=-center[1])
    for poly in getattr(local,'geoms',[local]):
        ax.plot(*poly.exterior.xy,color=color,lw=width,ls=style,zorder=8)


def scale_north(ax):
    ax.plot([-35,-25],[-35,-35],color='#303A42',lw=2,zorder=12)
    ax.text(-30,-32.7,'10 m',ha='center',fontsize=7.5,color='#303A42',zorder=12)
    ax.annotate('N',xy=(.92,.20),xytext=(.92,.065),xycoords='axes fraction',ha='center',va='center',
                fontsize=8,weight='bold',color='#303A42',arrowprops={'arrowstyle':'-|>','lw':1.4,'color':'#303A42'},zorder=12)


def draw_case_panel(fig,root,data,stats,out):
    pair_ids=list(stats['pair_ids']);cases=data.set_index('Build_ID')
    buildings,nodes,edges,details=diagnostics(root,data,pair_ids,out)
    diagnostic={r['Build_ID']:r for r in details}
    observed_bounds=[float(np.floor(nodes.observed_rate.min())),float(np.ceil(nodes.observed_rate.max()))]
    if observed_bounds[0]==observed_bounds[1]:observed_bounds[1]+=1
    residual_limit=max(2.,float(np.ceil(abs(nodes.residual_rate).max()*2)/2))
    rate_norm=Normalize(*observed_bounds);residual_norm=Normalize(-residual_limit,residual_limit)
    fig.text(.055,.455,'(c) Matched buildings: velocity planes and local differences',fontsize=11,weight='bold')
    counts=[int(cases.loc[bid,'PS_Count']) for bid in pair_ids]
    fig.text(.055,.434,f'Same road block; centroid separation {stats["primary_pair_distance_m"]:.0f} m. All {counts[0]} / {counts[1]} associated PS retained.',fontsize=8.4,color='#75828B')
    for col,(bid,color) in enumerate(zip(pair_ids,['#C5433C','#2875B5'])):
        case=cases.loc[bid];node=nodes[nodes.Build_ID.eq(bid)].sort_values('node');edge=edges[edges.Build_ID.eq(bid)];diag=diagnostic[bid]
        poly=buildings.loc[bid].geometry;center=np.array([poly.centroid.x,poly.centroid.y]);xy=node[['x','y']].to_numpy()-center
        left=.055+col*.481
        fig.text(left,.409,f'{bid}  |  {SHORT[case.static_class]} → {SHORT[case.insar_class]}  |  IBSI {case.IBSI:.3f}',fontsize=9.5,color=color,weight='bold')
        for j in range(2):
            ax=fig.add_axes([left+j*.224,.150,.202,.225])
            local=affinity.translate(poly,xoff=-center[0],yoff=-center[1])
            gpd.GeoSeries([local]).plot(ax=ax,facecolor='#F0F2F3',edgecolor='none',zorder=0)
            outline(ax,poly.buffer(5),center,'#8F989E',.65,'--');outline(ax,poly,center,color)
            if j==0:
                ax.scatter(xy[:,0],xy[:,1],c=node.observed_rate,cmap='viridis',norm=rate_norm,s=14,edgecolors='white',linewidths=.3,zorder=5)
                gx,gy=np.meshgrid(np.linspace(-40,40,161),np.linspace(-40,40,161));world=np.c_[gx.ravel()+center[0],gy.ravel()+center[1]]
                inside=Delaunay(node[['x','y']].to_numpy()).find_simplex(world)>=0
                slopes=np.array([diag['slope_x'],diag['slope_y']])
                plane=diag['mean_fitted_rate']+(world-np.array([diag['weighted_center_x'],diag['weighted_center_y']]))@slopes
                field=np.ma.masked_where(~inside.reshape(gx.shape),plane.reshape(gx.shape))
                contours=ax.contour(gx,gy,field,levels=np.arange(observed_bounds[0],observed_bounds[1]+.25,.5),colors='#34454F',linewidths=.65,zorder=4)
                labels=ax.clabel(contours,fmt='%.1f',inline=True,fontsize=7)
                for label in labels:label.set_path_effects([pe.withStroke(linewidth=2,foreground='white')])
                direction=slopes/np.linalg.norm(slopes)
                start=np.array([diag['weighted_center_x'],diag['weighted_center_y']])-center-direction*10
                arrow=ax.annotate('',xy=start+direction*20,xytext=start,arrowprops={'arrowstyle':'-|>','lw':1.6,'color':'#20272D'},zorder=11)
                arrow.arrow_patch.set_path_effects([pe.Stroke(linewidth=3,foreground='white'),pe.Normal()])
                title='Observed rate + fitted plane'
            else:
                segments=xy[edge[['left_node','right_node']].to_numpy(dtype=int)]
                ax.add_collection(LineCollection(segments,colors='#C4C9CD',linewidths=.35,alpha=.7,zorder=1))
                ax.scatter(xy[:,0],xy[:,1],c=node.residual_rate,cmap='RdBu_r',norm=residual_norm,s=16,edgecolors='white',linewidths=.25,zorder=4)
                flags=node.gradient_abnormal.to_numpy(dtype=bool)
                ring=ax.scatter(xy[flags,0],xy[flags,1],s=38,facecolors='none',edgecolors='#222222',linewidths=.8,zorder=6)
                ring.set_path_effects([pe.Stroke(linewidth=1.7,foreground='white'),pe.Normal()])
                title='Plane residual + local gradient'
            ax.set(xlim=(-40,40),ylim=(-40,40),aspect='equal',xticks=[-30,0,30],yticks=[-30,0,30])
            ax.set_title(title,fontsize=8,pad=5);ax.tick_params(labelsize=7.5,length=2,pad=2)
            ax.set_xlabel('Local easting (m)',fontsize=7.7,labelpad=2)
            if j==0:ax.set_ylabel('Local northing (m)',fontsize=7.7,labelpad=2)
            else:
                ax.set_ylabel('')
                ax.tick_params(labelleft=False)
            for spine in ax.spines.values():spine.set_visible(True)
            scale_north(ax)
        fig.text(left,.096,f'RMS {case.V_RMS:.3f} mm/yr  |  Tilt {case.Tilt_Angle:.6f}°/yr',fontsize=8.2)
        fig.text(left,.077,f'DGI {case.DGI_Str:.3f} mm m⁻¹ yr⁻¹  |  Q {case.Q_insar:.3f}',fontsize=8.2)
    for x,norm,cmap,label in [(.095,rate_norm,'viridis','Observed vertical rate (mm yr⁻¹)'),(.585,residual_norm,'RdBu_r','Rate minus fitted plane (mm yr⁻¹)')]:
        ax=fig.add_axes([x,.047,.32,.009]);cb=fig.colorbar(plt.cm.ScalarMappable(norm=norm,cmap=cmap),cax=ax,orientation='horizontal')
        cb.set_label(label,fontsize=8,labelpad=2);cb.ax.tick_params(labelsize=7,length=2,pad=2);cb.solids.set_rasterized(False)
    record={'panel':'c','type':'Matched building PS velocity planes and local gradients','building_ids':pair_ids,
            'window_m':[-40,40,-40,40],'observed_rate_color_bounds':observed_bounds,'residual_color_bounds':[-residual_limit,residual_limit],
            'associated_PS_records':counts,'all_PS_inside_common_windows':True,'plane_contours_limited_to_PS_convex_hull':True,
            'arrow_length_m':20,'arrow_meaning':'Direction of increasing fitted velocity, not displacement direction',
            'black_circles':'Point gradients strictly above each building own P90','observation_period':'2017-2019',
            'diagnostics':details,'scientific_interpretation':'Velocity-plane gradient and residuals do not measure structural inclination or twist directly.'}
    (out/'data/case_panel_diagnostics.json').write_text(json.dumps(record,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    return record
