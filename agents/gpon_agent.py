from agents.base_agent import BaseAgent
class GPONAgent(BaseAgent):
    name="GPONAgent"
    def on_event(self,e):
        super().on_event(e); p=e.get("payload",{}); out=[]
        if e.get("event_type")=="pon_telemetry" and (p.get("utilization_pct",0)>90):
            out.append({"source":self.name,"event_type":"gpon_congestion","asset_id":e["asset_id"],"severity":"warning","payload":{"evidence":p}})
        return out
