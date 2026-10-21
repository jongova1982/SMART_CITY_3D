from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from database.repository import meters_for_zone

@dataclass
class Transformer:
    transformer_id: str; zone_id: str; rated_kva: float=1000.0; outage: bool=False
    @property
    def loading_pct(self): return min(999.0,self.load_kva/self.rated_kva*100) if self.rated_kva else 0
    load_kva: float=0.0

class ElectricalGrid:
    def __init__(self, repository, seed=20261020):
        self.repository=repository; self.seed=seed
        self.transformers={f"TX-{z}-01":Transformer(f"TX-{z}-01",z) for z in "ABCD"}
        self.circuit_outages=set(); self.meter_states={}; self.energy_kwh={}; self.street_lights={f"LAMP-{z}-{i}":True for z in "ABCD" for i in range(4)}
        self.traffic_lights={f"TL-{z}-01":True for z in "ABCD"}
    def step(self, simulation_time: float, elapsed_seconds: float=1.0):
        import math
        out=[]
        for z,t in self.transformers.items():
            hour=(simulation_time/3600)%24; power=105+55*(1+math.sin((hour-7)*math.pi/12))/2
            t.load_kva=power/.94
            voltage=0.0 if t.outage else 230.0*(1-.04*max(0,t.loading_pct-70)/30)
            meters=meters_for_zone(self.repository,t.zone_id)
            for row in meters:
                m=row["meter_id"]; kw=power/len(meters); outage=t.outage or row["circuit_id"] in self.circuit_outages
                state={"meter_id":m,"zone_id":t.zone_id,"power_kw":0 if outage else kw,"energy_kwh":self.energy_kwh.get(m,0)+(0 if outage else kw*elapsed_seconds/3600),"voltage_v":0 if outage else voltage,"current_a":0 if outage else kw*1000/max(voltage,1)/.94,"power_factor":.94,"outage":outage,"loading_pct":t.loading_pct}
                self.energy_kwh[m]=state["energy_kwh"]; self.meter_states[m]=state
            out.append({"asset_id":z,"zone_id":t.zone_id,"event_type":"electrical_telemetry","severity":"critical" if t.outage else "info","payload":{"power_kw":power,"voltage_v":voltage,"loading_pct":t.loading_pct,"outage":t.outage}})
        return out
    def inject_transformer_outage(self, transformer_id): self.transformers[transformer_id].outage=True
    def restore_transformer(self, transformer_id): self.transformers[transformer_id].outage=False
