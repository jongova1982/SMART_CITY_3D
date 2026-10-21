from dataclasses import replace
from config.settings import Settings
from database.connection import connect
from scripts.seed_city import seed_city
from simulation.service import CitySimulation

def make_sim(tmp_path):
    settings=replace(Settings(),data_dir=tmp_path); seed_city(settings); conn=connect(settings.database_path); return conn,CitySimulation(conn)

def test_energy_and_gpon_simulation_and_restoration(tmp_path):
    conn,sim=make_sim(tmp_path)
    try:
        first=sim.step(); assert first["ont_online"]==5000
        assert sum(z["power_kw"] for z in first["zone_metrics"].values())>0
        assert sum(z["energy_kwh"] for z in first["zone_metrics"].values())>0
        sim.inject("transformer_outage","TX-A-01"); down=sim.step()
        assert down["zone_metrics"]["A"]["outage"]
        assert down["zone_metrics"]["A"]["ont_online"]==0
        assert down["ont_online"]==2800
        incidents=[e for e in down["events"] if e.get("event_type")=="correlated_incident"]
        assert incidents and incidents[0]["payload"]["affected_ont_count"]==2200
        sim.restore("transformer_outage","TX-A-01"); assert sim.step()["ont_online"]==5000
    finally: conn.close()

def test_fiber_cut_and_capacity_are_branch_limited(tmp_path):
    conn,sim=make_sim(tmp_path)
    try:
        sim.step(); port=next(iter(sim.gpon.ont_states.values()))["pon_port_id"]
        before=sum(o["online"] for o in sim.gpon.ont_states.values())
        sim.inject("fiber_cut",port); sim.step(); after=sum(o["online"] for o in sim.gpon.ont_states.values())
        assert 0 < before-after <= 64
    finally: conn.close()
