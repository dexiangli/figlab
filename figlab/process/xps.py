"""XPS exported spectra; no implicit energy calibration or refitting."""
from .base import SpectrumProcessor, register

@register
class XPSProcessor(SpectrumProcessor):
    name = 'xps'
    def geometry(self, rows):
        return {'n_points': len(rows)}
    def truncate(self, rows, geom, tail):
        return rows

def decorate(ax, groups, spec):
    import numpy as np
    for artist in list(ax.lines):
        artist.remove()
    if spec['data'].get('missing_spectrum'):
        ax.text(.5,.5,'N1s data not available',ha='center',va='center',transform=ax.transAxes,fontsize=7)
        ax.set_yticks([])
        return
    palette = spec['data'].get('peak_palette', ['#F5C46F','#DBB2FF','#628CBB','#C0688B','#397B76'])
    bgrows = groups.get('Background', [])
    bg = {float(r['binding_energy_eV']):float(r['intensity_cps']) for r, inc in bgrows if inc}
    peak_labels=[]
    for i, series in enumerate(spec['series']):
        name=series['curve']
        rows=[r for r, inc in groups.get(name,[]) if inc]
        if not rows or not series['include']: continue
        x=np.array([float(r['binding_energy_eV']) for r in rows]); y=np.array([float(r['intensity_cps']) for r in rows])
        y = y + float(series.get('off_y', 0))
        if spec['data'].get('survey_comparison'):
            ax.plot(x,y,color=series['color'],lw=spec['style']['line_width_pt'])
            ax.text(.97,(.87 if float(series.get('off_y',0)) else .36),name,ha='right',transform=ax.transAxes,color=series['color'],fontsize=6.5)
            continue
        if spec['data'].get('fit_only'):
            if name == 'Envelope':
                ax.plot(x,y,color=series['color'],lw=spec['style']['line_width_pt'],zorder=5)
            continue
        if name=='Measured' and not spec['data'].get('show_measured', True): continue
        if name=='Measured': ax.plot(x,y,'.',color='#333333',ms=spec['style'].get('xps_point_size_pt', .45),zorder=4)
        elif name=='Envelope': ax.plot(x,y,color=series['color'],lw=spec['style']['line_width_pt'],zorder=5)
        elif name=='Background': ax.plot(x,y,color=spec['data'].get('background_color','#8A6D9B'),lw=.7,zorder=3)
        else:
            base=np.array([bg.get(v,0) for v in x]); color=palette[(i-3)%len(palette)]
            for band in range(48):
                lo=band/48; hi=(band+1)/48
                ax.fill_between(x,base+(y-base)*lo,base+(y-base)*hi,color=color,alpha=.06+.64*hi,linewidth=0,zorder=1)
            ax.plot(x,y,color=color,lw=.65,zorder=2)
            if spec['data'].get('label_peaks'):
                signal=y-base; k=int(np.argmax(signal))
                region=spec['data'].get('region','')
                peak_labels.append((x[k],y[k],region))
    if peak_labels:
        low,high=ax.get_ylim()
        ax.set_ylim(low,high+(high-low)*.5)
    peak_labels.sort(reverse=spec['data'].get('reverse_energy',True))
    for j,(energy,height,region) in enumerate(peak_labels):
        position=.16+.68*j/max(1,len(peak_labels)-1) if len(peak_labels)>1 else .55
        ax.annotate(f'{region}\n{energy:.1f} eV',xy=(energy,height),xytext=(position,.91),textcoords='axes fraction',ha='center',va='top',fontsize=5.5,arrowprops=dict(arrowstyle='->',lw=.4,shrinkA=3,shrinkB=3))
    if spec['data'].get('reverse_energy',True): ax.invert_xaxis()
    if spec['data'].get('hide_y_ticks', False): ax.set_yticks([])
