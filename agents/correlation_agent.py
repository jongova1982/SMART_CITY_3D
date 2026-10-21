from agents.base_agent import BaseAgent
from collections import deque
class CorrelationAgent(BaseAgent):
    name="CorrelationAgent"
    def __init__(self): super().__init__(); self.events=deque(maxlen=500)
    def on_event(self,e):
        super().on_event(e); self.events.append(e); result=[]
        if e.get("event_type")=="energy_anomaly" and e.get("payload",{}).get("evidence",{}).get("outage"):
            z=e.get("zone_id"); others=[x for x in self.events if x.get("event_type")=="pon_telemetry" and x.get("payload",{}).get("online",True) is False]
            result.append({"source":self.name,"event_type":"correlated_incident","asset_id":e["asset_id"],"zone_id":z,"severity":"critical","payload":{"hypothesis":"Transformer outage may explain dependent GPON interruption","confidence":0.88 if others else 0.64,"evidence":[e["asset_id"],f"zone {z}",f"{len(others)} recent GPON interruption events"],"affected_ont_count":0}})
        return result
    def correlate_transformer_outage(self, transformer_id, zone_id, affected_onts):
        """Produce a topology-based hypothesis with explicit synthetic evidence."""
        return {"source":self.name,"event_type":"correlated_incident","asset_id":transformer_id,"zone_id":zone_id,"severity":"critical","payload":{"hypothesis":"Transformer outage explains the loss of power to dependent ONTs in this zone","confidence":0.92 if affected_onts else 0.55,"evidence":[f"transformer={transformer_id}",f"zone={zone_id}",f"dependent_onts_without_power={affected_onts}","dependency path: transformer -> circuit -> meter -> ONT"],"affected_ont_count":affected_onts,"method":"deterministic topology correlation; synthetic data"}}
