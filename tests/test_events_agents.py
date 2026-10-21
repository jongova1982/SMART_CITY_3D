from communications.schemas import CityEvent
from agents.forecast_agents import LoadForecastAgent, NetworkForecastAgent

def test_versioned_event_and_forecasts():
    event=CityEvent(simulation_time=12,source="test",asset_id="TX-A-01",event_type="electrical_telemetry",payload={"power_kw":12})
    assert event.schema_version==1 and event.event_id
    load=LoadForecastAgent(); assert load.forecast(10)>0 and load.mae>=0
    network=NetworkForecastAgent(); assert network.forecast("PON-001",30)==30
