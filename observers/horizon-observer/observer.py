#!/usr/bin/env python3
"""Horizon Observer: local apparent Solar System geometry for Wiesmoor."""
from __future__ import annotations

import json, math, os, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    import ephem  # type: ignore
    EPHEM_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised in minimal CI images
    ephem = None  # type: ignore
    EPHEM_AVAILABLE = False

OBSERVER_ID = "horizon-observer"
LOCAL_TZ = ZoneInfo("Europe/Berlin")
LOCATION = {"name":"Wiesmoor","region":"East Frisia","country":"Germany","latitude":53.4167,"longitude":7.7333,"elevation_m":8,"timezone":"Europe/Berlin"}
PRIMARY = [("sun","Sun","star","sun"),("moon","Moon","moon","moon"),("mercury","Mercury","planet","mercury"),("venus","Venus","planet","venus"),("mars","Mars","planet","mars"),("jupiter","Jupiter","planet","jupiter"),("saturn","Saturn","planet","saturn")]
COMPASS = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
CONSTELLATIONS = [
    ("ursa-major","Ursa Major","11:03:43","+61:45:03",1,"spring/northern"),("ursa-minor","Ursa Minor","15:00:00","+75:00:00",2,"circumpolar"),("cassiopeia","Cassiopeia","01:20:00","+60:00:00",3,"autumn/circumpolar"),("cygnus","Cygnus","20:36:00","+42:00:00",4,"summer"),("lyra","Lyra","18:37:00","+38:48:00",5,"summer"),("aquila","Aquila","19:50:00","+08:52:00",6,"summer"),("orion","Orion","05:35:00","-05:23:00",1,"winter"),("taurus","Taurus","04:35:00","+16:30:00",7,"winter"),("gemini","Gemini","07:04:00","+22:36:00",8,"winter"),("leo","Leo","10:08:00","+11:58:00",6,"spring"),("scorpius","Scorpius","16:29:00","-26:26:00",9,"summer/low"),("sagittarius","Sagittarius","18:55:00","-25:00:00",9,"summer/low"),("pegasus","Pegasus","22:43:00","+19:28:00",8,"autumn"),("andromeda","Andromeda","00:42:00","+41:16:00",7,"autumn")]

def now_utc() -> datetime:
    raw=os.environ.get("WORLD_OBSERVER_NOW_UTC","").strip()
    if raw:
        return datetime.fromisoformat(raw.replace("Z","+00:00")).astimezone(timezone.utc).replace(microsecond=0)
    return datetime.now(timezone.utc).replace(microsecond=0)

def iso(dt: datetime|None) -> str|None:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00","Z") if dt else None

def iso_local(dt: datetime|None) -> str|None:
    return dt.astimezone(LOCAL_TZ).isoformat() if dt else None

def normalize_azimuth(deg: float) -> float:
    return deg % 360.0

def compass_direction(azimuth_deg: float) -> str:
    # 16 equal sectors of 22.5 degrees; N is centered on 0°, so boundaries are 11.25°, 33.75°, ...
    return COMPASS[int((normalize_azimuth(azimuth_deg) + 11.25) // 22.5) % 16]

def sky_light_state(solar_altitude_deg: float) -> dict[str, Any]:
    if solar_altitude_deg >= 0: state,label,intensity,warm,stars="day","Day",1.0,1.0,0.0
    elif solar_altitude_deg >= -6: state,label,intensity,warm,stars="civil_twilight","Civil twilight",0.65,0.55,0.15
    elif solar_altitude_deg >= -12: state,label,intensity,warm,stars="nautical_twilight","Nautical twilight",0.35,0.25,0.45
    elif solar_altitude_deg >= -18: state,label,intensity,warm,stars="astronomical_twilight","Astronomical twilight",0.15,0.08,0.75
    else: state,label,intensity,warm,stars="night","Night",0.0,0.0,1.0
    return {"state":state,"solar_altitude_deg":round(solar_altitude_deg,2),"label":label,"frontend_intensity":intensity,"warm_glow_intensity":warm,"star_field_visibility":stars}

def geometric_visibility(alt: float, kind: str) -> str:
    if kind == "star": return "daylight" if alt > 0 else "below_horizon"
    if alt <= 0: return "below_horizon"
    if alt <= 5: return "low"
    if alt <= 15: return "fair"
    return "good"

def display_visibility(geom: str, ambient: str, kind: str) -> str:
    return geom if kind == "star" or geom in {"below_horizon","unavailable"} else ("daylight_limited" if ambient == "day" else geom)

def _jd(dt: datetime) -> float:
    dt=dt.astimezone(timezone.utc); y,m=dt.year,dt.month
    d=dt.day+(dt.hour+(dt.minute+dt.second/60)/60)/24
    if m<=2: y-=1; m+=12
    a=math.floor(y/100); b=2-a+math.floor(a/4)
    return math.floor(365.25*(y+4716))+math.floor(30.6001*(m+1))+d+b-1524.5

def _norm(deg: float) -> float: return deg % 360.0

def _sun_ra_dec(jd: float) -> tuple[float,float]:
    n=jd-2451545.0; L=_norm(280.460+0.9856474*n); g=math.radians(_norm(357.528+0.9856003*n)); lam=math.radians(_norm(L+1.915*math.sin(g)+0.020*math.sin(2*g))); eps=math.radians(23.439-0.0000004*n)
    return math.degrees(math.atan2(math.cos(eps)*math.sin(lam), math.cos(lam)))%360, math.degrees(math.asin(math.sin(eps)*math.sin(lam)))

def _body_ra_dec(body: str, jd: float) -> tuple[float,float]:
    if body == "sun": return _sun_ra_dec(jd)
    n=jd-2451545.0
    if body == "moon":
        L=_norm(218.316+13.176396*n); M=math.radians(_norm(134.963+13.064993*n)); F=math.radians(_norm(93.272+13.229350*n)); lon=math.radians(_norm(L+6.289*math.sin(M))); lat=math.radians(5.128*math.sin(F)); eps=math.radians(23.439)
        x=math.cos(lon)*math.cos(lat); y=math.sin(lon)*math.cos(lat)*math.cos(eps)-math.sin(lat)*math.sin(eps); z=math.sin(lon)*math.cos(lat)*math.sin(eps)+math.sin(lat)*math.cos(eps)
        return math.degrees(math.atan2(y,x))%360, math.degrees(math.asin(z))
    periods={"mercury":87.969,"venus":224.701,"mars":686.98,"jupiter":4332.59,"saturn":10759.22}; offsets={"mercury":60,"venus":95,"mars":145,"jupiter":35,"saturn":210}
    lon=_norm(offsets[body]+360*n/periods[body]); eps=math.radians(23.439); lr=math.radians(lon)
    return math.degrees(math.atan2(math.cos(eps)*math.sin(lr), math.cos(lr)))%360, math.degrees(math.asin(math.sin(eps)*math.sin(lr)))

def _altaz_from_radec(ra: float, dec: float, dt: datetime) -> tuple[float,float]:
    jd=_jd(dt); T=(jd-2451545.0)/36525; gmst=_norm(280.46061837+360.98564736629*(jd-2451545.0)+0.000387933*T*T-T*T*T/38710000); lst=_norm(gmst+LOCATION["longitude"]); ha=math.radians(((lst-ra+540)%360)-180); lat=math.radians(LOCATION["latitude"]); dr=math.radians(dec)
    alt=math.asin(math.sin(lat)*math.sin(dr)+math.cos(lat)*math.cos(dr)*math.cos(ha))
    az=math.atan2(-math.sin(ha), math.tan(dr)*math.cos(lat)-math.sin(lat)*math.cos(ha))
    return math.degrees(alt), normalize_azimuth(math.degrees(az))

def observer_at(dt: datetime) -> Any:
    if not EPHEM_AVAILABLE: return None
    obs=ephem.Observer(); obs.lat=str(LOCATION["latitude"]); obs.lon=str(LOCATION["longitude"]); obs.elevation=LOCATION["elevation_m"]; obs.date=ephem.Date(dt); obs.pressure=0
    return obs

def to_dt(d: Any) -> datetime: return ephem.Date(d).datetime().replace(tzinfo=timezone.utc)

def resolve_body(body_identifier: Any) -> Any:
    if not EPHEM_AVAILABLE:
        return str(body_identifier)
    if callable(body_identifier):
        return body_identifier
    constructors = {
        "sun": ephem.Sun,
        "moon": ephem.Moon,
        "mercury": ephem.Mercury,
        "venus": ephem.Venus,
        "mars": ephem.Mars,
        "jupiter": ephem.Jupiter,
        "saturn": ephem.Saturn,
    }
    return constructors[str(body_identifier).lower()]

def calc_body(body_cls: Any, dt: datetime) -> tuple[Any,float,float]:
    if EPHEM_AVAILABLE:
        obs=observer_at(dt); b=body_cls(); b.compute(obs); return b, math.degrees(float(b.alt)), normalize_azimuth(math.degrees(float(b.az)))
    ra,dec=_body_ra_dec(str(body_cls), _jd(dt)); alt,az=_altaz_from_radec(ra,dec,dt)
    return {"ra":ra,"dec":dec}, alt, az

def rise_set(body_cls: Any, dt: datetime) -> dict[str, Any]:
    out={"rise_time_utc":None,"rise_time_local":None,"rise_status":"unavailable","set_time_utc":None,"set_time_local":None,"set_status":"unavailable","next_event_type":None,"next_event_timestamp_utc":None,"next_event_timestamp_local":None,"event_status":"ok"}
    if EPHEM_AVAILABLE:
        obs=observer_at(dt); body=body_cls(); events=[]
        for name, fn in (("rise", obs.next_rising),("set", obs.next_setting)):
            try:
                t=to_dt(fn(body)); out[f"{name}_time_utc"]=iso(t); out[f"{name}_time_local"]=iso_local(t); out[f"{name}_status"]="ok"; events.append((t,name))
            except ephem.AlwaysUpError: out[f"{name}_status"]="circumpolar_always_up"; out["event_status"]="circumpolar"
            except ephem.NeverUpError: out[f"{name}_status"]="never_rises"; out["event_status"]="never_rises"
            except Exception as exc: out[f"{name}_status"]="event_calculation_error"; out["event_error"]=str(exc)
        if events:
            t,n=min(events); out["next_event_type"]=n; out["next_event_timestamp_utc"]=iso(t); out["next_event_timestamp_local"]=iso_local(t)
        return out
    # Local fallback: scan next 48h for geometric horizon crossings.
    vals=[]; step=timedelta(minutes=20); t0=dt
    prev_t=t0; prev=calc_body(body_cls, prev_t)[1]
    for i in range(1,145):
        cur_t=t0+step*i; cur=calc_body(body_cls, cur_t)[1]
        if (prev <= 0 < cur) or (prev > 0 >= cur):
            name="rise" if cur>prev else "set"; out[f"{name}_time_utc"]=iso(cur_t); out[f"{name}_time_local"]=iso_local(cur_t); out[f"{name}_status"]="ok"; vals.append((cur_t,name))
        prev_t,prev=cur_t,cur
    if vals:
        t,n=min(vals); out["next_event_type"]=n; out["next_event_timestamp_utc"]=iso(t); out["next_event_timestamp_local"]=iso_local(t)
    else:
        out["event_status"]="no_crossing_in_48h"
    return out

def moon_phase(dt: datetime) -> dict[str, Any]:
    syn=29.53058867; age=(_jd(dt)-2451550.1)%syn; illum=(1-math.cos(2*math.pi*age/syn))/2*100
    if EPHEM_AVAILABLE:
        _m, _alt, _az = calc_body(ephem.Moon, dt); illum=float(getattr(_m,"phase",illum)); prev=to_dt(ephem.previous_new_moon(ephem.Date(dt))); nxt=to_dt(ephem.next_new_moon(ephem.Date(dt))); syn=(nxt-prev).total_seconds()/86400; age=(dt-prev).total_seconds()/86400
    names=[(1.845,"New Moon"),(5.536,"Waxing Crescent"),(9.228,"First Quarter"),(12.919,"Waxing Gibbous"),(16.611,"Full Moon"),(20.302,"Waning Gibbous"),(23.994,"Last Quarter"),(27.685,"Waning Crescent"),(99,"New Moon")]
    return {"illumination_fraction":round(illum/100,4),"illumination_percent":round(illum,1),"age_days":round(age,2),"phase_name":next(n for lim,n in names if age < lim),"waxing_waning":"waxing" if age < syn/2 else "waning"}

def samples(body_cls: Any, start: datetime) -> list[dict[str, Any]]:
    rows=[]
    for i in range(49):
        t=start+timedelta(minutes=30*i); _b, alt, az=calc_body(body_cls,t); rows.append({"timestamp_utc":iso(t),"timestamp_local":iso_local(t),"altitude_deg":round(alt,2),"azimuth_deg":round(az,2)})
    return rows

def build_constellations(dt: datetime, limit:int=10) -> list[dict[str,Any]]:
    rows=[]
    if EPHEM_AVAILABLE:
        obs=observer_at(dt)
        for ident,name,ra,dec,prio,season in CONSTELLATIONS:
            star=ephem.FixedBody(); star._ra=ephem.hours(ra); star._dec=ephem.degrees(dec); star.compute(obs); alt=math.degrees(float(star.alt)); az=normalize_azimuth(math.degrees(float(star.az)))
            if alt >= 10: rows.append({"identifier":ident,"display_name":name,"anchor_ra":ra,"anchor_dec":dec,"altitude_deg":round(alt,2),"azimuth_deg":round(az,2),"compass_direction":compass_direction(az),"above_horizon":True,"label_priority":prio,"seasonal_relevance":season})
    else:
        for ident,name,ra,dec,prio,season in CONSTELLATIONS:
            h,m,sec=[float(x) for x in ra.split(":")]; sign=-1 if dec.startswith("-") else 1; dd=dec.replace("+","").replace("-",""); d,am,asec=[float(x) for x in dd.split(":")]
            ra_deg=(h+m/60+sec/3600)*15; dec_deg=sign*(d+am/60+asec/3600); alt,az=_altaz_from_radec(ra_deg,dec_deg,dt)
            if alt >= 10: rows.append({"identifier":ident,"display_name":name,"anchor_ra":ra,"anchor_dec":dec,"altitude_deg":round(alt,2),"azimuth_deg":round(az,2),"compass_direction":compass_direction(az),"above_horizon":True,"label_priority":prio,"seasonal_relevance":season})
    return sorted(rows, key=lambda r:(r["label_priority"], -r["altitude_deg"]))[:limit]

def _galactic_to_equatorial(l_deg: float, b_deg: float=0.0) -> tuple[float,float]:
    # J2000 transformation constants for the Galactic north pole and node.
    ra_ngp=math.radians(192.85948); dec_ngp=math.radians(27.12825); l_omega=math.radians(32.93192)
    l=math.radians(l_deg); b=math.radians(b_deg)
    dec=math.asin(math.sin(b)*math.sin(dec_ngp)+math.cos(b)*math.cos(dec_ngp)*math.sin(l_omega-l))
    ra=math.atan2(math.cos(b)*math.cos(l_omega-l), math.sin(b)*math.cos(dec_ngp)-math.cos(b)*math.sin(dec_ngp)*math.sin(l_omega-l))+ra_ngp
    return math.degrees(ra)%360, math.degrees(dec)

def milky_way(dt: datetime) -> dict[str, Any]:
    points=[]; seg=0; prev_az=None; prev_vis=False
    for idx,l in enumerate(range(0,360,10)):
        if EPHEM_AVAILABLE:
            obs=observer_at(dt); eq=ephem.Equatorial(ephem.Galactic(math.radians(l),0)); fb=ephem.FixedBody(); fb._ra=eq.ra; fb._dec=eq.dec; fb.compute(obs); alt=math.degrees(float(fb.alt)); az=normalize_azimuth(math.degrees(float(fb.az))); ra_s=str(eq.ra); dec_s=str(eq.dec)
        else:
            ra,dec=_galactic_to_equatorial(l); alt,az=_altaz_from_radec(ra,dec,dt); ra_s=round(ra,3); dec_s=round(dec,3)
        vis=alt>0
        if idx and (abs(az-(prev_az or 0))>180 or (vis != prev_vis and vis)): seg += 1
        points.append({"sequence":idx,"segment_id":seg,"galactic_longitude_deg":l,"right_ascension":ra_s,"declination":dec_s,"altitude_deg":round(alt,2),"azimuth_deg":round(az,2),"above_horizon":vis})
        prev_az=az; prev_vis=vis
    return {"description":"Approximate geometrical Galactic equator path; actual visibility depends on darkness, weather, moonlight and light pollution.","sample_count":len(points),"points":points,"segments_available":len({p['segment_id'] for p in points if p['above_horizon']})}

def iss_status(dt: datetime) -> dict[str, Any]:
    path=Path("data/reference/iss.tle")
    if not path.exists(): return {"status":"unavailable","reason":"local_tle_missing","tle_path":str(path),"network_dependency":False}
    return {"status":"unavailable","reason":"tle_calculation_not_enabled","tle_path":str(path),"network_dependency":False}

def build_payload(calculation_time: datetime|None=None) -> dict[str, Any]:
    started=datetime.now(timezone.utc); t=(calculation_time or now_utc()).astimezone(timezone.utc).replace(microsecond=0); errors=[]; warnings=[]
    sun_obj,sun_alt,_=calc_body(resolve_body("sun"),t); sky=sky_light_state(sun_alt); objects=[]
    for ident,name,typ,cls in PRIMARY:
        try:
            body_cls=resolve_body(cls); b,alt,az=calc_body(body_cls,t); geom=geometric_visibility(alt, typ if ident=="sun" else typ); ev=rise_set(body_cls,t); meta={"colour_token": ident if ident in {"sun","moon","mercury","venus","mars","jupiter","saturn"} else "default_planet","symbol_type":typ}
            if ident=="moon": meta.update(moon_phase(t))
            objects.append({"id":ident,"display_name":name,"object_type":typ,"calculated_at_utc":iso(t),"altitude_deg":round(alt,2),"azimuth_deg":round(az,2),"compass_direction":compass_direction(az),"above_horizon":alt>0,"geometric_visibility":geom,"ambient_light_state":sky["state"],"display_visibility":display_visibility(geom, sky["state"], typ if ident=="sun" else typ),**ev,"display_metadata":meta,"altitude_series_24h":samples(body_cls,t)})
        except Exception as exc: errors.append(f"{ident}: {exc}")
    const=build_constellations(t); mw=milky_way(t); iss=iss_status(t); above=[o for o in objects if o["above_horizon"]]; highest=max(objects,key=lambda o:o["altitude_deg"],default={"id":None,"altitude_deg":None})
    scene={"objects":sorted([{ "object_id":o["id"],"label":o["display_name"],"altitude_deg":o["altitude_deg"],"azimuth_deg":o["azimuth_deg"],"compass_direction":o["compass_direction"],"above_horizon":o["above_horizon"],"display_priority":10-i,"symbol_type":o["display_metadata"]["symbol_type"],"suggested_label_placement":"above" if o["altitude_deg"]<60 else "side","colour_token":o["display_metadata"]["colour_token"],"apparent_size_token":"large" if o["id"] in {"sun","moon"} else "medium" if o["id"] in {"venus","jupiter"} else "small"} for i,o in enumerate(objects)], key=lambda r:(not r["above_horizon"],-r["display_priority"]))}
    moon=next((o for o in objects if o["id"]=="moon"),{})
    sent=f"{', '.join(o['display_name'] for o in above[:3]) or 'No primary objects'}{' and more' if len(above)>3 else ''} {'are' if len(above)!=1 else 'is'} currently above the Wiesmoor geometric horizon during {sky['label'].lower()}."
    finished=datetime.now(timezone.utc)
    return {"observer":{"id":OBSERVER_ID,"name":"Horizon Observer","category":"earth-and-space","version":1},"observer_id":OBSERVER_ID,"observer_name":"Horizon Observer","date_utc":t.date().isoformat(),"generated_at":iso(t),"collected_at_utc":iso(t),"location":LOCATION,"status":"ok" if not errors else "partial","data_status":"ok" if not errors else "partial","summary":{"objects_above_horizon_count":len(above),"bright_planets_above_horizon_count":sum(1 for o in above if o['object_type']=='planet' and o['id'] not in {'uranus','neptune'}),"sun_altitude_deg":round(sun_alt,2),"moon_altitude_deg":moon.get("altitude_deg"),"moon_illumination_percent":moon.get("display_metadata",{}).get("illumination_percent"),"ambient_light_state":sky["state"],"highest_object_id":highest["id"],"highest_object_altitude_deg":highest["altitude_deg"],"iss_status":iss["status"],"constellation_labels_available":len(const),"milky_way_segments_available":mw["segments_available"],"status_sentence":sent},"sky_state":sky,"orientation":{"zenith_altitude_deg":90,"north_azimuth_deg":0,"east_azimuth_deg":90,"south_azimuth_deg":180,"west_azimuth_deg":270,"compass_ticks":[{"direction":d,"azimuth_deg":i*22.5} for i,d in enumerate(COMPASS)]},"objects":objects,"horizon_scene":scene,"constellations":const,"milky_way":mw,"iss":iss,"diagnostics":{"calculation_started_at":iso(started),"calculation_finished_at":iso(finished),"duration_ms":round((finished-started).total_seconds()*1000,2),"astronomy_engine":"PyEphem" if EPHEM_AVAILABLE else "Built-in approximate local astronomy","astronomy_engine_version":getattr(ephem,"__version__",None) if EPHEM_AVAILABLE else None,"object_calculations_attempted":len(PRIMARY),"object_calculations_successful":len(objects),"constellation_anchor_count":len(CONSTELLATIONS),"milky_way_sample_count":mw["sample_count"],"local_network_requests":0,"external_api_requests":0,"iss_adapter_status":iss["status"],"warnings":warnings + ([iss["reason"]] if iss["status"]=="unavailable" else []),"errors":errors},"sources":[{"name":"Local PyEphem astronomical calculations","type":"local_calculation","external_runtime_api":False,"notes":["Wiesmoor canonical coordinates reused from Wiesmoor Sky Observer.","Geometric horizon without terrain obstruction modelling; atmospheric pressure is set to zero to avoid refraction correction.","Constellation labels are approximate anchor points, not official boundaries.","Milky Way path is a geometrical Galactic-equator approximation."]}]}

def main() -> None:
    json.dump(build_payload(), sys.stdout, ensure_ascii=False, sort_keys=True); sys.stdout.write("\n")
if __name__ == "__main__": main()
