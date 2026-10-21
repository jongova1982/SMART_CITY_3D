from dataclasses import replace

from config.settings import Settings
from database.connection import connect
from database.repository import acknowledge_alarm
from dashboard.data_provider import SimulationData
from scripts.seed_city import seed_city
from simulation.service import CitySimulation


def test_dashboard_projections_use_live_models_and_paginate_gpon(tmp_path):
    settings = replace(Settings(), data_dir=tmp_path)
    seed_city(settings)
    conn = connect(settings.database_path)
    try:
        sim = CitySimulation(conn)
        sim.step()
        view = SimulationData(sim)
        summary = view.summary()
        assert summary["ont_total"] == 5000
        assert summary["ont_online"] == 5000
        assert summary["power_kw"] > 0
        assert len(view.gpon_rows(offset=0, limit=100)) == 100
        assert len(view.gpon_rows(offset=100, limit=100)) == 100
        assert view.gpon_rows(search="ONT-A-0001", limit=100)[0][0] == "ONT-A-0001"
        assert len(view.electrical_rows(zone="A")) > 0
        assert len(view.agent_rows()) == 6
        detail = view.ont_details("ONT-A-0001")
        assert detail["olt_id"] == "OLT-A-01"
        assert detail["online"] and detail["rx_dbm"] < 0
    finally:
        conn.close()


def test_alarm_acknowledgement_persists_and_reset_clears_live_faults(tmp_path):
    settings = replace(Settings(), data_dir=tmp_path)
    seed_city(settings)
    conn = connect(settings.database_path)
    try:
        sim = CitySimulation(conn)
        sim.step()
        event = sim.inject("transformer_outage", "TX-A-01")
        acknowledge_alarm(conn, event["event_id"])
        assert SimulationData(sim).summary()["alarms"] == 1
        assert next(row for row in SimulationData(sim).alarm_rows() if row[0] == event["event_id"])[-1] == "Reconocida"
        sim.reset()
        assert sim.engine.simulation_time == 0
        assert SimulationData(sim).summary()["alarms"] == 0
    finally:
        conn.close()
