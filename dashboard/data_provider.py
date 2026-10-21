"""Read-side projections for the PySide6 operations center."""
from __future__ import annotations

from datetime import datetime, timezone
from database.repository import alarm_status


class SimulationData:
    """Build lightweight views from the coordinator's existing live models."""

    def __init__(self, simulation):
        self.simulation = simulation

    def summary(self):
        sim = self.simulation
        result = sim.last_result
        zones = result.get("zone_metrics", sim.zone_metrics())
        online = result.get("ont_online", sum(o["online"] for o in sim.gpon.ont_states.values()))
        total = result.get("ont_total", len(sim.gpon.ont_states))
        return {
            "ont_total": total, "ont_online": online, "ont_offline": total-online,
            "pon_ports": len(sim._port_loads()),
            "power_kw": sum(z["power_kw"] for z in zones.values()),
            "energy_kwh": sum(z["energy_kwh"] for z in zones.values()),
            "transformers": sum(not t.outage for t in sim.grid.transformers.values()),
            "signals": sum(sim.grid.traffic_lights.values()),
            "lighting": sum(sim.grid.street_lights.values()),
            "alarms": (sum(t.outage for t in sim.grid.transformers.values()) + len(sim.gpon.fiber_cuts) +
                       sum(v >= 90 for v in sim.gpon.pon_overrides.values()) +
                       sum(not v for v in sim.grid.traffic_lights.values()) +
                       sum(not v for v in sim.grid.street_lights.values())),
            "agents": len(sim.agents), "simulation_time": sim.engine.simulation_time,
            "zones": zones,
        }

    def electrical_rows(self, zone="Todas", status="Todos"):
        sim = self.simulation
        rows = []
        for meter_id, state in sim.grid.meter_states.items():
            if zone != "Todas" and state["zone_id"] != zone:
                continue
            healthy = not state["outage"]
            label = "Normal" if healthy else "Sin servicio"
            if status != "Todos" and label != status:
                continue
            rows.append((meter_id, state["zone_id"], state["power_kw"], state["energy_kwh"],
                         state["voltage_v"], state["current_a"], state["power_factor"], label))
        return rows

    def gpon_rows(self, search="", offset=0, limit=100):
        sim = self.simulation
        needle = search.strip().upper()
        rows = []
        for ont_id, state in sim.gpon.ont_states.items():
            if needle and needle not in ont_id.upper() and needle not in state["pon_port_id"].upper():
                continue
            rows.append((ont_id, state["zone_id"], state["pon_port_id"], state["rx_dbm"],
                         state["traffic_mbps"], "Conectada" if state["online"] else "Desconectada",
                         "Con energía" if state["powered"] else "Sin energía"))
            if len(rows) >= offset + limit:
                break
        return rows[offset:offset + limit]

    def ont_details(self, ont_id):
        row = self.simulation.conn.execute(
            "SELECT o.ont_id,o.zone_id,o.pon_port_id,o.splitter_id,o.meter_id,o.subscriber_number, "
            "s.split_ratio,p.olt_id,m.circuit_id FROM onts o "
            "JOIN splitters s USING(splitter_id) JOIN pon_ports p USING(pon_port_id) "
            "JOIN meters m USING(meter_id) WHERE o.ont_id=?", (ont_id,)
        ).fetchone()
        if row is None:
            return None
        info = dict(row)
        state = self.simulation.gpon.ont_states.get(ont_id, {})
        meter = self.simulation.grid.meter_states.get(info["meter_id"], {})
        alarms = [event for event in self.simulation.events if event.get("asset_id") in
                  (ont_id, info["pon_port_id"], info["meter_id"])]
        return {
            **info,
            "online": state.get("online", False), "powered": state.get("powered", False),
            "rx_dbm": state.get("rx_dbm", 0.0), "tx_dbm": state.get("tx_dbm", 0.0),
            "traffic_mbps": state.get("traffic_mbps", 0.0),
            "power_kw": meter.get("power_kw", 0.0), "energy_kwh": meter.get("energy_kwh", 0.0),
            "alarms": alarms,
        }

    def agent_rows(self):
        sim = self.simulation
        hour = (sim.engine.simulation_time / 3600) % 24
        rows = []
        for agent in sim.agents:
            heartbeat = agent.last_heartbeat or "Sin pulso registrado"
            prediction = "—"
            method = "Reglas sintéticas"
            if agent.name == "LoadForecastAgent":
                prediction = f"{agent.forecast(hour):.1f} kW · MAE {agent.mae:.2f} · RMSE {agent.rmse:.2f}"
                method = f"RandomForest · {agent.train_samples} train / {agent.test_samples} prueba"
            elif agent.name == "NetworkForecastAgent":
                prediction = f"{len(agent.history)} puertos con historial"
                method = "Promedio móvil de perfil sintético"
            elif agent.name == "CorrelationAgent":
                prediction = f"{len(agent.events)} eventos en ventana"
                method = "Correlación determinista por topología"
            rows.append((agent.name, "Disponible", heartbeat, agent.events_seen, prediction, method))
        return rows

    def urban_rows(self):
        sim = self.simulation
        rows = []
        for asset_id, healthy in sim.grid.traffic_lights.items():
            rows.append((asset_id, asset_id.split("-")[1], "Semáforo", "Operativo" if healthy else "Falla"))
        for asset_id, healthy in sim.grid.street_lights.items():
            rows.append((asset_id, asset_id.split("-")[1], "Alumbrado", "Encendido" if healthy else "Falla"))
        return rows

    def alarm_rows(self):
        rows = []
        for event in self.simulation.events:
            if event.get("severity") not in ("warning", "critical"):
                continue
            rows.append((event.get("event_id", ""), event.get("timestamp_utc", "")[:19].replace("T", " "),
                         event.get("zone_id") or "—", event.get("asset_id", ""), event.get("severity", ""),
                         event.get("event_type", ""), str(event.get("payload", {}))[:180],
                         alarm_status(self.simulation.conn, event.get("event_id", ""))))
        return rows

