from agents.base_agent import BaseAgent
class EnergyAgent(BaseAgent):
    name="EnergyAgent"
    def on_event(self,e):
        super().on_event(e); p=e.get("payload",{}); out=[]
        if e.get("event_type")=="electrical_telemetry" and (p.get("outage") or p.get("loading_pct",0)>90 or p.get("voltage_v",230)<207):
            out.append({"source":self.name,"event_type":"energy_anomaly","zone_id":e.get("zone_id"),"asset_id":e["asset_id"],"severity":"critical" if p.get("outage") else "warning","payload":{"evidence":{k:p.get(k) for k in ("outage","loading_pct","voltage_v")}}})
        return out
