from __future__ import annotations
from database.repository import onts, port_loads

class GPONNetwork:
    def __init__(self, repository):
        self.repository=repository; self.fiber_cuts=set(); self.pon_overrides={}; self.ont_states={}
    def step(self, meter_states):
        events=[]
        for row in onts(self.repository):
            ont=row["ont_id"]; port=row["pon_port_id"]; zone=row["zone_id"]
            powered=not meter_states.get(row["meter_id"],{}).get("outage",False)
            link=powered and port not in self.fiber_cuts
            tx=2.0; fiber_km=.4 + (int(row["subscriber_number"])%30)/100
            rx=tx-fiber_km*.35-10.5-1.2-.6
            state={"ont_id":ont,"zone_id":zone,"pon_port_id":port,"tx_dbm":tx,"rx_dbm":rx,"fiber_km":fiber_km,"traffic_mbps":(int(row["subscriber_number"])%80)*.1 if link else 0,"online":link,"los":not link,"powered":powered,"utilization_pct":self.pon_overrides.get(port,35.0)}
            self.ont_states[ont]=state
        for port, count in port_loads(self.repository).items():
            events.append({"asset_id":port,"event_type":"pon_telemetry","severity":"warning" if self.pon_overrides.get(port,35)>=90 else "info","payload":{"ont_count":count,"utilization_pct":self.pon_overrides.get(port,35)}})
        return events
    def cut_fiber(self, port_id): self.fiber_cuts.add(port_id)
    def restore_fiber(self, port_id): self.fiber_cuts.discard(port_id)
