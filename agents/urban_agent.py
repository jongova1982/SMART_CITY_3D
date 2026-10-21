from agents.base_agent import BaseAgent
class UrbanAgent(BaseAgent):
    name="UrbanAgent"
    def on_event(self,e):
        super().on_event(e)
        kind=e.get("payload",{}).get("fault_type")
        if e.get("event_type") in ("street_light_failure","traffic_light_failure") or (e.get("event_type")=="simulated_fault_command" and kind in ("street_light_failure","traffic_light_failure")):
            return [{"source":self.name,"event_type":"urban_incident","zone_id":e.get("zone_id"),"asset_id":e["asset_id"],"severity":"warning" if e.get("payload",{}).get("action")!="restored" else "info","payload":{"observation":"Simulated urban equipment fault","fault_type":kind or e.get("event_type")}}]
        return []
