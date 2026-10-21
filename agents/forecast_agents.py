from agents.base_agent import BaseAgent
import numpy as np
from sklearn.ensemble import IsolationForest, RandomForestRegressor

class LoadForecastAgent(BaseAgent):
    name="LoadForecastAgent"
    def __init__(self):
        super().__init__(); x=np.arange(0,24*30); self.model=RandomForestRegressor(n_estimators=30,max_depth=8,random_state=42,n_jobs=1); y=130+45*np.sin((x%24-7)*np.pi/12)+np.random.default_rng(42).normal(0,3,len(x)); split=int(len(x)*.8); self.model.fit(x[:split].reshape(-1,1),y[:split]); pred=self.model.predict(x[split:].reshape(-1,1)); self.mae=float(np.mean(np.abs(pred-y[split:]))); self.rmse=float(np.sqrt(np.mean((pred-y[split:])**2))); self.train_samples=split; self.test_samples=len(x)-split
    def forecast(self, hour): return float(self.model.predict(np.array([[hour%24]]))[0])
class NetworkForecastAgent(BaseAgent):
    name="NetworkForecastAgent"
    def __init__(self): super().__init__(); self.history={}
    def forecast(self, port, utilization):
        hist=self.history.setdefault(port,[]); hist.append(float(utilization)); hist[:]=hist[-24:]; return float(np.mean(hist[-5:])) if hist else 0
class _IsolationRule:
    def __init__(self):
        self.model=IsolationForest(contamination=.04,random_state=42,n_estimators=80).fit(np.random.default_rng(42).normal(size=(300,3)))
    def anomalous(self, values): return bool(self.model.predict([values])[0]<0)
