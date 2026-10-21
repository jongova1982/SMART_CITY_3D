from __future__ import annotations
import random

class SimulationEngine:
    def __init__(self, seed: int = 20261020, step_seconds: float = 1.0):
        self.rng=random.Random(seed); self.step_seconds=step_seconds; self.simulation_time=0.0; self.tick=0
    def advance(self):
        self.simulation_time += self.step_seconds; self.tick += 1
        return self.simulation_time
    def daily_factor(self):
        hour=(self.simulation_time/3600)%24
        return .65 + .35 * (1 + __import__('math').sin((hour-7)*__import__('math').pi/12))/2
