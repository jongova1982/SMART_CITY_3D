from __future__ import annotations
from datetime import datetime, timezone
from uuid import uuid4
import json
from database.repository import save_telemetry
from simulation.engine import SimulationEngine
from simulation.electrical_grid import ElectricalGrid
from simulation.gpon_network import GPONNetwork
from simulation.fault_injector import FaultInjector
from communications.schemas import CityEvent
from agents.energy_agent import EnergyAgent
from agents.gpon_agent import GPONAgent
from agents.forecast_agents import LoadForecastAgent, NetworkForecastAgent
from agents.urban_agent import UrbanAgent
from agents.correlation_agent import CorrelationAgent

class CitySimulation:
    def __init__(self, conn, seed=20261020):
        self.conn=conn; self.seed=seed; self.engine=SimulationEngine(seed); self.grid=ElectricalGrid(conn,seed); self.gpon=GPONNetwork(conn); self.faults=FaultInjector(self.grid,self.gpon)
        self.agents=[EnergyAgent(),LoadForecastAgent(),GPONAgent(),NetworkForecastAgent(),UrbanAgent(),CorrelationAgent()]
        self.events=[]; self.last_result={}
        self.broker=None
    def step(self):
        now=self.engine.advance(); records=self.grid.step(now,self.engine.step_seconds)
        onts=self.gpon.step(self.grid.meter_states); records += onts
        # Fan out compact aggregate events to each agent and persist all outputs.
        emitted=[]
        for r in records:
            event=CityEvent(simulation_time=now,source=r.get("source","simulation"),zone_id=r.get("zone_id"),asset_id=r["asset_id"],event_type=r["event_type"],severity=r["severity"],payload=r["payload"])
            emitted.append(event.model_dump(mode="json"))
            for agent in self.agents:
                for diagnosis in agent.on_event(event.model_dump(mode="json")):
                    diagnosis.setdefault("simulation_time",now); diagnosis.setdefault("zone_id",r.get("zone_id")); emitted.append(diagnosis)
        load_agent=next(a for a in self.agents if isinstance(a,LoadForecastAgent))
        network_agent=next(a for a in self.agents if isinstance(a,NetworkForecastAgent))
        hour=(now/3600)%24
        for zone in "ABCD":
            emitted.append({"schema_version":1,"source":load_agent.name,"event_type":"load_forecast","zone_id":zone,"asset_id":f"TX-{zone}-01","severity":"info","simulation_time":now,"payload":{"forecast_kw":load_agent.forecast(hour),"model":"RandomForestRegressor synthetic profile","validation_mae_kw":round(load_agent.mae,3)}})
        for port,count in self._port_loads().items():
            utilization=next((r["payload"]["utilization_pct"] for r in records if r["asset_id"]==port),35.0)
            prediction=network_agent.forecast(port,utilization)
            if self.engine.tick%10==0:
                emitted.append({"schema_version":1,"source":network_agent.name,"event_type":"pon_utilization_forecast","asset_id":port,"severity":"warning" if prediction>=90 else "info","simulation_time":now,"payload":{"forecast_utilization_pct":prediction,"history_points":len(network_agent.history[port])}})
        correlator=next(a for a in self.agents if isinstance(a,CorrelationAgent))
        for zone,t in ((z,self.grid.transformers[f"TX-{z}-01"]) for z in "ABCD"):
            if t.outage:
                affected=sum(1 for o in self.gpon.ont_states.values() if o["zone_id"]==zone and not o["powered"])
                emitted.append(correlator.correlate_transformer_outage(t.transformer_id,zone,affected)|{"simulation_time":now})
        save_telemetry(self.conn,datetime.now(timezone.utc).isoformat(),now,emitted)
        if self.broker:
            for raw in emitted:
                try: self.broker.publish(CityEvent.model_validate(raw))
                except Exception: continue
        self.events=(emitted+self.events)[:500]
        self.last_result={"simulation_time":now,"zone_metrics":self.zone_metrics(),"ont_online":sum(1 for x in self.gpon.ont_states.values() if x["online"]),"ont_total":len(self.gpon.ont_states),"events":self.events[:100]}
        return self.last_result
    def zone_metrics(self):
        result={}
        for z in "ABCD":
            t=self.grid.transformers[f"TX-{z}-01"]
            state=[m for m in self.grid.meter_states.values() if m["zone_id"]==z]
            result[z]={"power_kw":sum(m["power_kw"] for m in state),"energy_kwh":sum(m["energy_kwh"] for m in state),"voltage_v":state[0]["voltage_v"] if state else 230,"loading_pct":t.loading_pct,"outage":t.outage,"ont_online":sum(1 for o in self.gpon.ont_states.values() if o["zone_id"]==z and o["online"])}
        return result
    def inject(self,kind,asset_id):
        self.faults.inject(kind,asset_id); return self._record_fault(kind,asset_id,"injected")
    def restore(self,kind,asset_id):
        self.faults.restore(kind,asset_id); return self._record_fault(kind,asset_id,"restored")
    def _record_fault(self,kind,asset_id,action):
        zone=asset_id.split("-")[1] if asset_id.startswith(("TX-","OLT-","LAMP-","TL-")) else None
        event={"schema_version":1,"event_id":str(uuid4()),"timestamp_utc":datetime.now(timezone.utc).isoformat(),"simulation_time":self.engine.simulation_time,"source":"FaultInjector","zone_id":zone,"asset_id":asset_id,"event_type":"simulated_fault_command","severity":"critical" if action=="injected" else "info","payload":{"fault_type":kind,"action":action,"simulated":True}}
        self.events.insert(0,event)
        for agent in self.agents:
            self.events[0:0]=agent.on_event(event)
        save_telemetry(self.conn,event["timestamp_utc"],self.engine.simulation_time,[event])
        return event
    def _port_loads(self):
        from database.repository import port_loads
        return port_loads(self.conn)
    def attach_broker(self,broker): self.broker=broker

    def reset(self):
        """Reset live model state while retaining inventory and event history."""
        self.engine=SimulationEngine(self.seed, self.engine.step_seconds)
        self.grid=ElectricalGrid(self.conn, self.seed)
        self.gpon=GPONNetwork(self.conn)
        self.faults=FaultInjector(self.grid,self.gpon)
        for agent in self.agents:
            agent.events_seen=0
            agent.last_heartbeat=None
            if hasattr(agent,"history"):
                agent.history.clear()
        self.last_result={}
