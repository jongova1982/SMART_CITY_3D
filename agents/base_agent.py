from __future__ import annotations
from datetime import datetime, timezone
from uuid import uuid4

class BaseAgent:
    name="BaseAgent"
    def __init__(self): self.last_heartbeat=None; self.events_seen=0
    def heartbeat(self):
        self.last_heartbeat=datetime.now(timezone.utc).isoformat(); return {"schema_version":1,"event_id":str(uuid4()),"timestamp_utc":self.last_heartbeat,"source":self.name,"event_type":"heartbeat","payload":{"events_seen":self.events_seen}}
    def on_event(self,event): self.events_seen+=1; return []
