"""Measure local simulation tick throughput and event-write latency."""
from __future__ import annotations
import argparse, statistics, time, tempfile
from dataclasses import replace
from pathlib import Path
from config.settings import load_settings
from database.connection import connect, initialize_schema
from scripts.seed_city import seed_city
from simulation.service import CitySimulation

def benchmark(iterations=15):
    settings=replace(load_settings(),data_dir=Path(tempfile.mkdtemp(prefix="jongox-benchmark-"))); seed_city(settings); conn=connect(settings.database_path); initialize_schema(conn)
    try:
        sim=CitySimulation(conn,settings.random_seed); samples=[]
        for _ in range(iterations):
            start=time.perf_counter(); sim.step(); samples.append(time.perf_counter()-start)
        ordered=sorted(samples)
        return {"iterations":iterations,"tick_ms_median":statistics.median(samples)*1000,"tick_ms_p95":ordered[min(len(ordered)-1,int(len(ordered)*.95))]*1000,"simulated_ont":len(sim.gpon.ont_states),"telemetry_rows":conn.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0]}
    finally: conn.close()

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--iterations",type=int,default=15); print(benchmark(p.parse_args().iterations))
