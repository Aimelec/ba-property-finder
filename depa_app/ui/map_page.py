"""Página Mapa: Leaflet (tiles oscuros de CARTO) dentro de Qt WebEngine."""
import json
from urllib.parse import unquote

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import TitleLabel

from ..opendata import safety as seguridad, stations
from ..domain import geo
from .common import BG, dim_label, meters, miles, score_color
from .filters import FilterPanel

HTML = """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>
<style>
html,body,#map{height:100%;margin:0;background:__BG__;font-family:'Segoe UI',sans-serif}
.leaflet-popup-content-wrapper,.leaflet-popup-tip{background:#1e2128;color:#e6e6e6;border-radius:12px}
.leaflet-popup-content{margin:12px 14px;width:250px!important}
.pp img{width:100%;height:140px;object-fit:cover;border-radius:8px;display:block;margin-bottom:8px}
.pp .pr{font-size:18px;font-weight:600}.pp .sc{float:right;font-weight:700;font-size:16px}
.pp .dim{color:#9aa3ad;font-size:12px;margin:2px 0}
.pp a.b{display:inline-block;margin:8px 6px 0 0;padding:5px 10px;border-radius:6px;background:#2bd4a4;color:#0d0f12;text-decoration:none;font-weight:600}
.pp a.b2{background:#2c313a;color:#e6e6e6}
.leaflet-tooltip{background:#1e2128;color:#e6e6e6;border:1px solid #333}
.legend{background:rgba(30,33,40,.92);color:#e6e6e6;padding:8px 12px;border-radius:10px;font-size:12px;line-height:18px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}
.leaflet-control-layers{background:#1e2128;color:#e6e6e6;border:none!important}
.leaflet-bar a{background:#1e2128;color:#e6e6e6;border-color:#333}
</style></head><body><div id="map"></div><script>
const map=L.map('map',{preferCanvas:true,zoomControl:true,maxZoom:16}).setView([-34.50,-58.55],11);
const esri='https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/';
L.tileLayer(esri+'World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
 {attribution:'Tiles &copy; Esri, HERE, Garmin, &copy; OpenStreetMap',maxZoom:16}).addTo(map);
L.tileLayer(esri+'World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}',{maxZoom:16,pane:'shadowPane'}).addTo(map);
const subLayer=L.layerGroup().addTo(map), stLayer=L.layerGroup().addTo(map), ringLayer=L.layerGroup(),
      pLayer=L.layerGroup().addTo(map), link=L.layerGroup().addTo(map);
const ctl=L.control.layers(null,{'Subte':subLayer,'Estaciones de tren':stLayer,'Radio ideal a estación':ringLayer,
  'Propiedades':pLayer},{collapsed:false}).addTo(map);
const calorPane=map.createPane('calor');  // debajo de propiedades y estaciones
calorPane.style.zIndex=350; calorPane.style.pointerEvents='none';
const lg=L.control({position:'bottomleft'});
lg.onAdd=()=>{const d=L.DomUtil.create('div','legend');d.innerHTML=
 '<b>Puntaje</b><br><i style="background:#2bd4a4"></i>alto<br><i style="background:#f5a524"></i>medio<br><i style="background:#e5484d"></i>bajo<br><i style="background:#fff;border:2px solid #7aa2ff"></i>estación de tren<br><i style="background:#0d0f12;border:2px solid #c618cc"></i>subte (color de la línea)'+
 '<br><i style="background:linear-gradient(90deg,#3b2a7a,#e5484d,#ffd166);border-radius:2px;width:22px"></i>delitos violentos (CABA)'+
 '<br><i style="background:rgba(255,122,69,.35);border:2px solid #ff7a45;border-radius:2px"></i>barrio popular (RENABAP)';return d};
lg.addTo(map);
let markers={}, first=true, stations=[];
function setSeguridad(heat, barrios){
  // CABA: celdas [lat,lng,hechos]; 'max' ~ percentil 95 para que se vean las diferencias
  if(heat.cells.length && L.heatLayer){
    const hl=L.heatLayer(heat.cells,{radius:16,blur:18,max:heat.max,minOpacity:.15,maxZoom:15,
      gradient:{.2:'#3b2a7a',.5:'#a3306b',.75:'#e5484d',1:'#ffd166'}});
    // al alejar se suman más celdas por píxel (x4 por nivel); leaflet.heat compensa x2: el resto acá
    const scale=()=>hl.setOptions({max:heat.max*Math.pow(2,Math.max(0,15-map.getZoom()))});
    hl.on('add',()=>{map.getPane('calor').appendChild(hl._canvas); scale();});
    map.on('zoomend',scale);
    hl.addTo(map); ctl.addOverlay(hl,'Delitos violentos CABA ('+heat.years.join('–')+')');
  }
  if(barrios.features.length){
    const bl=L.geoJSON(barrios,{style:{color:'#ff7a45',weight:1.5,fillColor:'#ff7a45',fillOpacity:.25},
      onEachFeature:(f,l)=>{const p=f.properties; l.bindTooltip('Barrio popular · '+(p.tipo||'')+'<br>'+(p.nombre||'')+
        ' ('+(p.localidad||p.partido||'')+')'+(p.familias?'<br>~'+p.familias+' familias':''));}});
    bl.addTo(map); ctl.addOverlay(bl,'Barrios populares GBA Norte (RENABAP)');
  }
}
function setStations(list, ideal){
  stations=list; stLayer.clearLayers(); ringLayer.clearLayers();
  for(const s of list){
    L.circleMarker([s.lat,s.lng],{radius:4,color:'#7aa2ff',weight:2,fillColor:'#fff',fillOpacity:1})
     .bindTooltip(s.name+(s.line?' · '+s.line:'')).addTo(stLayer);
    L.circle([s.lat,s.lng],{radius:ideal,color:'#7aa2ff',weight:1,opacity:.4,fillOpacity:.05,interactive:false}).addTo(ringLayer);
  }
}
function setSubte(d){
  subLayer.clearLayers();
  const col={};
  for(const ln of d.lines){
    col[ln.line]=ln.color;
    for(const p of ln.paths) L.polyline(p,{color:ln.color,weight:4,opacity:.85,interactive:false}).addTo(subLayer);
  }
  for(const s of d.stations){
    L.circleMarker([s.lat,s.lng],{radius:4,color:col[s.line]||'#ccc',weight:2,fillColor:'#0d0f12',fillOpacity:1})
     .bindTooltip('Subte '+(s.line||'')+' · '+s.name).addTo(subLayer);
  }
}
function setData(list){
  pLayer.clearLayers(); link.clearLayers(); markers={};
  const b=[];
  for(const p of list){
    const m=L.circleMarker([p.lat,p.lng],{radius:p.fav?9:7,color:p.fav?'#ffd166':'#0d0f12',weight:p.fav?3:1,
      fillColor:p.color,fillOpacity:.9}).bindPopup(p.html,{maxWidth:280});
    m.on('popupopen',()=>{link.clearLayers(); if(p.st) L.polyline([[p.lat,p.lng],p.st],{color:'#7aa2ff',dashArray:'6 6',weight:2}).addTo(link);});
    m.on('popupclose',()=>link.clearLayers());
    m.addTo(pLayer); markers[p.id]=m; b.push([p.lat,p.lng]);
  }
  if(first && b.length){map.fitBounds(b,{padding:[30,30],maxZoom:14}); first=false;}
}
function focusOn(id){const m=markers[id]; if(!m) return false; map.setView(m.getLatLng(),15); m.openPopup(); return true;}
</script></body></html>"""


class Page(QWebEnginePage):
    """Intercepta los links depa://ficha/<id> y depa://abrir/<url> del popup."""
    action = Signal(str, str)

    def acceptNavigationRequest(self, url, nav_type, is_main):
        if url.scheme() == "depa":
            self.action.emit(url.host(), unquote(url.path().lstrip("/")))
            return False
        if nav_type == QWebEnginePage.NavigationTypeLinkClicked:
            QDesktopServices.openUrl(url)
            return False
        return True


class MapPage(QWidget):
    def __init__(self, state, go_to_listing, parent=None):
        super().__init__(parent)
        self.setObjectName("mapa")
        self.state = state
        self.go_to_listing = go_to_listing
        self.ready = False
        self.pending_focus = None
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 12, 12)
        head = QHBoxLayout()
        head.addWidget(TitleLabel("Mapa", self))
        self.count = dim_label("", self)
        head.addSpacing(16)
        head.addWidget(self.count, 1)
        root.addLayout(head)
        body = QHBoxLayout()
        body.addWidget(FilterPanel(state, self))
        self.view = QWebEngineView(self)
        self.page = Page(self.view)
        self.page.setBackgroundColor(BG)
        self.page.action.connect(self._action)
        self.view.setPage(self.page)
        self.view.loadFinished.connect(self._loaded)
        self.view.setHtml(HTML.replace("__BG__", BG), QUrl("https://depa.local/"))
        body.addWidget(self.view, 1)
        root.addLayout(body, 1)
        state.data_changed.connect(self.refresh)
        state.filters_changed.connect(self.refresh)

    def _loaded(self, ok):
        self.ready = ok
        if ok:
            st = [{"name": s["name"], "line": s["line"], "lat": s["lat"], "lng": s["lng"]}
                  for s in self.state.stations]
            heat = seguridad.load_heat()
            counts = sorted(c[2] for c in heat["cells"])
            heat["max"] = counts[int(len(counts) * 0.95)] if counts else 1
            heat.pop("sources", None)
            # primero los barrios: comparten el lienzo con propiedades y estaciones y quedan debajo
            self.page.runJavaScript(f"setSeguridad({json.dumps(heat)}, "
                                    f"{json.dumps(seguridad.load_barrios(), ensure_ascii=False)})")
            self.page.runJavaScript(f"setStations({json.dumps(st)}, {self.state.settings['estacion_ideal_m']})")
            self.page.runJavaScript(f"setSubte({json.dumps(self.state.subte, ensure_ascii=False)})")
            self.refresh()
        else:
            self.count.setText("No se pudo cargar el mapa (¿sin internet?).")

    def refresh(self):
        if not self.ready:
            return
        rows = [r for r in self.state.filtered() if r["lat"] is not None]
        data = []
        for r in rows:
            st = self.state.station_of(r)
            data.append({
                "id": r["id"], "lat": r["lat"], "lng": r["lng"], "fav": bool(r.get("favorite")),
                "color": score_color(r["score"]).name(),
                "st": [st["lat"], st["lng"]] if st else None,
                "html": self._popup(r),
            })
        self.page.runJavaScript(f"setData({json.dumps(data, ensure_ascii=False)})")
        self.count.setText(f"{len(rows)} propiedades en el mapa (las que no se pudieron ubicar no aparecen)")
        if self.pending_focus:
            self.focus(self.pending_focus)
            self.pending_focus = None

    def _popup(self, r):
        esc = lambda s: (s or "").replace("&", "&amp;").replace("<", "&lt;")
        img = f'<img src="{r["photo"]}">' if r.get("photo") else ""
        bits = [r["tipo"]]
        if r["amb"]:
            bits.append(f"{r['amb']:.0f} amb.")
        m2 = r["m2_cub"] or r["m2_tot"]
        if m2:
            bits.append(f"{m2:.0f} m²")
        if r["ppm2"]:
            bits.append(f"USD {miles(r['ppm2'])}/m²")
        st = ""
        if r["station_m"] is not None:
            st = (f"Estación {esc(r['station'])} · {meters(r['station_m'])} · "
                  f"~{geo.walk_minutes(r['station_m'])} min")
        if r.get("subte_m") is not None and r["subte_m"] <= 1500:
            st += (f"<br>Subte {esc(r['subte_line'])} {esc(r['subte'])} · {meters(r['subte_m'])} · "
                   f"~{geo.walk_minutes(r['subte_m'])} min")
        price = f"USD {miles(r['price_usd'])}" if r["price_usd"] else miles(r["price_ars"], "$ ")
        color = score_color(r["score"]).name()
        return (f'<div class="pp">{img}<span class="sc" style="color:{color}">{r["score"]}</span>'
                f'<div class="pr">{price}</div><div class="dim">{esc(r["address"])}</div>'
                f'<div class="dim">{" · ".join(bits)}</div><div class="dim">{st}</div>'
                f'<a class="b" href="depa://ficha/{r["id"]}">Ver ficha</a>'
                f'<a class="b b2" href="depa://abrir/{QUrl.toPercentEncoding(r["url"]).data().decode()}">Argenprop</a></div>')

    def focus(self, lid):
        if not self.ready:
            self.pending_focus = lid
            return
        self.page.runJavaScript(f"focusOn({json.dumps(lid)})")

    def _action(self, kind, value):
        if kind == "ficha":
            self.go_to_listing(value)
        elif kind == "abrir":
            QDesktopServices.openUrl(QUrl(value))
