from __future__ import annotations
import zmq

class EventBroker:
    """Local ZeroMQ PUB/SUB event relay. Bind once in the supervising process."""
    def __init__(self, endpoint="tcp://127.0.0.1:5557", context=None):
        self.endpoint=endpoint; self.context=context or zmq.Context.instance(); self.socket=None
    def start(self):
        self.socket=self.context.socket(zmq.PUB); self.socket.setsockopt(zmq.LINGER,0); self.socket.bind(self.endpoint)
    def publish(self, event):
        if self.socket is None: raise RuntimeError("Broker not started")
        self.socket.send_json(event.model_dump(mode="json"))
    def close(self):
        if self.socket: self.socket.close(0); self.socket=None

def subscriber(endpoint="tcp://127.0.0.1:5557", context=None):
    ctx=context or zmq.Context.instance(); sock=ctx.socket(zmq.SUB); sock.setsockopt(zmq.LINGER,0); sock.connect(endpoint); sock.setsockopt_string(zmq.SUBSCRIBE,""); return sock
