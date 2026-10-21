class FaultInjector:
    def __init__(self, grid, gpon): self.grid=grid; self.gpon=gpon
    def inject(self, kind, asset_id):
        if kind=="transformer_outage": self.grid.inject_transformer_outage(asset_id)
        elif kind=="fiber_cut": self.gpon.cut_fiber(asset_id)
        elif kind=="pon_saturation": self.gpon.pon_overrides[asset_id]=98.0
        elif kind=="street_light_failure": self.grid.street_lights[asset_id]=False
        elif kind=="traffic_light_failure": self.grid.traffic_lights[asset_id]=False
        else: raise ValueError(f"Unsupported simulated fault: {kind}")
    def restore(self, kind, asset_id):
        if kind=="transformer_outage": self.grid.restore_transformer(asset_id)
        elif kind=="fiber_cut": self.gpon.restore_fiber(asset_id)
        elif kind=="pon_saturation": self.gpon.pon_overrides.pop(asset_id,None)
        elif kind=="street_light_failure": self.grid.street_lights[asset_id]=True
        elif kind=="traffic_light_failure": self.grid.traffic_lights[asset_id]=True
        else: raise ValueError(f"Unsupported simulated fault: {kind}")
