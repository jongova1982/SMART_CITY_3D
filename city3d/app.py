"""Procedural low-poly city visualizer built without downloaded assets."""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

from direct.showbase.ShowBase import ShowBase
from direct.gui.OnscreenText import OnscreenText
from direct.gui.DirectGui import DirectButton, DirectFrame
from city3d.layout import (
    ARTERIAL_CENTERS, ARTERIAL_CURB_OFFSET, ARTERIAL_SIDEWALK_OFFSET,
    ARTERIAL_SIDEWALK_WIDTH, ARTERIAL_WIDTH, CITY_CENTERS, DISTRICT_SIZE,
    LOCAL_SIDEWALK_OFFSET, LOCAL_SIDEWALK_WIDTH, LOCAL_WIDTH,
    MAX_BUILDING_FOOTPRINT, building_lots,
)
from panda3d.core import (
    AmbientLight, BitMask32, CollisionBox, CollisionHandlerQueue,
    CollisionNode, CollisionRay, CollisionTraverser, DirectionalLight,
    Geom, GeomNode, GeomTriangles, GeomVertexData, GeomVertexFormat,
    GeomVertexWriter, TextNode, Vec4, ClockObject, Filename, TransparencyAttrib,
    LineSegs, PNMImage, Texture,
)


_CUBE_VERTS = (
    (-.5,-.5,-.5),(.5,-.5,-.5),(.5,.5,-.5),(-.5,.5,-.5),
    (-.5,-.5,.5),(.5,-.5,.5),(.5,.5,.5),(-.5,.5,.5),
)
_CUBE_TRIS = (
    (0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),
    (1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7),
)
_CUBE_FACES = ((0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7))


class SmartCityApp(ShowBase):
    """A readable, efficient city model: buildings are batched by material."""

    def __init__(self, config_path: Path | None = None, command_queue=None, selection_queue=None) -> None:
        super().__init__()
        path = config_path or Path(__file__).resolve().parents[1] / "config/city_config.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        from panda3d.core import WindowProperties
        props = WindowProperties()
        props.setTitle("JONGOX Smart City | Visor 3D")
        props.setSize(1440, 900)
        if hasattr(self.win, "requestProperties"):
            self.win.requestProperties(props)

        self.disableMouse()
        self.setBackgroundColor(.035, .055, .075, 1)
        self.camLens.setFov(52)
        self._camera_pivot = self.render.attachNewNode("camera-orbit-pivot")
        self.camera.wrtReparentTo(self._camera_pivot)
        self._selected = None
        self._selected_node = None
        self._command_queue = command_queue
        self._selection_queue = selection_queue
        self._previous_mouse = None
        self._keys_down = set()
        self._layers = {"electrical": True, "gpon": True}
        self.layers = {"electrical": [], "gpon": []}
        self._assets = {}
        self._traffic_signals = []
        self._intersection_signals = {}
        self._cars = []
        self._pedestrians = []
        self._simulation_time = 0.0
        self._paused = False
        self._time_of_day_override = None
        self._quality_mode = "MEDIUM"
        self._quality_buttons = {}
        self._zone_buttons = {}
        self._layer_buttons = {}
        self._time_buttons = {}
        self._pause_button = None
        self._active_zone = "A"
        self._quality_nodes = []
        self._lit_window_nodes = []
        self._lamp_bulbs = []
        self._lighting_elapsed = 0.0
        self._perf_elapsed = 0.0
        self._perf_frames = 0
        self._perf_refresh_elapsed = 0.0
        self._set_camera_home()
        self._lights()

        self._picker = CollisionTraverser("asset-picker")
        self._pick_queue = CollisionHandlerQueue()
        self._mouse_ray = CollisionRay()
        ray_node = CollisionNode("mouse-ray")
        ray_node.addSolid(self._mouse_ray)
        ray_node.setFromCollideMask(BitMask32.bit(1))
        ray_node.setIntoCollideMask(BitMask32.allOff())
        self._picker.addCollider(self.camera.attachNewNode(ray_node), self._pick_queue)

        self._build_city(cfg)
        self._make_hud()
        self._update_city(0.0)
        self.accept("r", self._set_camera_home)
        for key in ("w", "a", "s", "d", "arrow_up", "arrow_down", "arrow_left", "arrow_right", "q", "e", "+", "=", "-", "_"):
            self.accept(key, self._key_down, [key])
            self.accept(f"{key}-up", self._key_up, [key])
        self.accept("1", self._toggle_layer, ["electrical"])
        self.accept("2", self._toggle_layer, ["gpon"])
        self.accept("wheel_up", self._zoom, [.88])
        self.accept("wheel_down", self._zoom, [1.14])
        self.accept("mouse1", self._select_asset)
        self.taskMgr.add(self._mouse_update, "orbit-camera")
        self.taskMgr.add(self._animate_city, "animate-traffic-and-signals")
        self.taskMgr.add(self._poll_dashboard_commands, "dashboard-command-bridge")

    def _poll_dashboard_commands(self, task):
        if self._command_queue is None:
            return task.cont
        for _ in range(16):
            try:
                command = self._command_queue.get_nowait()
            except Exception:
                break
            action = command.get("action") if isinstance(command, dict) else None
            if action == "pause":
                paused = bool(command.get("paused"))
                if paused != self._paused:
                    self._toggle_pause()
            elif action == "reset":
                self._reset_simulation()
            elif action == "time":
                self._set_time_of_day(command.get("mode"))
            elif action == "zone":
                self._focus_zone(command.get("zone", "A"))
            elif action == "layers":
                mode = command.get("mode")
                self._set_layer_enabled("electrical", mode in ("both", "electrical"))
                self._set_layer_enabled("gpon", mode in ("both", "gpon"))
            elif action == "select_asset":
                self._focus_asset(command.get("asset_id", ""))
        return task.cont

    def _focus_asset(self, asset_id):
        node = self._assets.get(asset_id)
        if node is None:
            zone = None
            if asset_id.startswith(("ONT-", "MTR-", "TL-", "LAMP-")):
                parts = asset_id.split("-")
                zone = parts[1] if len(parts) > 1 and parts[1] in "ABCD" else None
            elif asset_id.startswith("PON-"):
                try:
                    port = int(asset_id.split("-")[1])
                    zone = "A" if port <= 35 else "B" if port <= 57 else "C" if port <= 67 else "D"
                except (ValueError, IndexError):
                    zone = None
            if zone:
                node = self._assets.get(f"OLT-{zone}-01") or self._assets.get(f"TX-{zone}-01")
        if node is None or node.isEmpty():
            return False
        if self._selected_node and not self._selected_node.isEmpty():
            self._selected_node.clearColorScale()
        self._selected = asset_id
        self._selected_node = node
        node.setColorScale(1.35, 1.25, .72, 1)
        position = node.getPos(self.render)
        self._camera_pivot.setPos(position.x, position.y, 0)
        self._camera_distance = 42.0
        self._place_camera_at_distance()
        self.camera.lookAt(0, 0, 1)
        self._hud_selection.setText(f"Activo seleccionado: {asset_id}")
        return True

    def _set_layer_enabled(self, name, enabled):
        self._layers[name] = enabled
        for node in self.layers[name]:
            node.show() if enabled else node.hide()
        for label, button in self._layer_buttons.items():
            self._style_control_button(button, active=self._layers[label])

    def _set_camera_home(self):
        self._camera_distance = 178.0
        self._camera_pivot.setPos(0, 0, 0)
        self._camera_pivot.setHpr(0, 0, 0)
        # The pivot is the point the camera orbits and pans around. Keeping the
        # camera aimed at the pivot makes zoom and keyboard movement predictable.
        self._place_camera_at_distance()
        self.camera.lookAt(0, 0, 1)
        self._previous_mouse = None

    def _place_camera_at_distance(self):
        # Lower the camera as it approaches street level so roads stay visible
        # between buildings when the user zooms in.
        height_ratio = min(.57, max(.22, self._camera_distance * .57 / 75.0))
        depth_ratio = math.sqrt(1.0 - height_ratio * height_ratio)
        self.camera.setPos(0, -self._camera_distance * depth_ratio,
                           self._camera_distance * height_ratio)

    def _lights(self):
        self._ambient_light = AmbientLight("soft-sky-light")
        self._ambient_light.setColor(Vec4(.48, .52, .57, 1))
        self.render.setLight(self.render.attachNewNode(self._ambient_light))
        self._sun_light = DirectionalLight("day-night-sun")
        self._sun_light.setColor(Vec4(.82, .78, .69, 1))
        self._sun_node = self.render.attachNewNode(self._sun_light)
        self._sun_node.setHpr(-38, -48, 0)
        self.render.setLight(self._sun_node)

    @staticmethod
    def _make_grain_texture(name, base, spread, seed):
        """Create a small repeating aggregate texture without external assets."""
        rng = random.Random(seed)
        image = PNMImage(64, 64, 3)
        for y in range(64):
            for x in range(64):
                grain = rng.uniform(-spread, spread)
                fleck = rng.uniform(1.0, 1.16) if rng.random() < .035 else 1.0
                image.setXel(x, y, *(max(0, min(1, channel*fleck+grain)) for channel in base))
        texture = Texture(name)
        texture.load(image)
        texture.setWrapU(Texture.WMRepeat)
        texture.setWrapV(Texture.WMRepeat)
        texture.setMinfilter(Texture.FTLinearMipmapLinear)
        texture.setMagfilter(Texture.FTLinear)
        return texture

    @staticmethod
    def _make_button_texture(name, aspect, fill, border):
        """Build a lightweight rounded cyan button with a thin red outline."""
        height = 128
        width = max(128, int(height * aspect))
        radius = height * .22
        stroke = max(3, height * .026)
        image = PNMImage(width, height, 4)
        image.alphaFill(0)
        for y in range(height):
            for x in range(width):
                qx = abs(x + .5 - width / 2) - (width / 2 - radius)
                qy = abs(y + .5 - height / 2) - (height / 2 - radius)
                outside = (math.hypot(max(qx, 0), max(qy, 0))
                           + min(max(qx, qy), 0) - radius)
                if outside <= 0:
                    color = border if outside >= -stroke else fill
                    image.setXelA(x, y, *color)
        texture = Texture(name)
        texture.load(image)
        texture.setWrapU(Texture.WMClamp)
        texture.setWrapV(Texture.WMClamp)
        texture.setMinfilter(Texture.FTLinear)
        texture.setMagfilter(Texture.FTLinear)
        return texture

    @staticmethod
    def _make_facade_texture(name, style, seed):
        """Tile a restrained low-resolution material pattern over batched walls."""
        rng = random.Random(seed)
        image = PNMImage(64, 64, 3)
        for y in range(64):
            for x in range(64):
                if style == "brick":
                    seam = y % 16 < 2 or (x + (8 if (y//16)%2 else 0)) % 24 < 2
                    shade = .66 if seam else .96
                elif style == "metal":
                    shade = .73 if x % 8 < 2 else (.84 if y % 18 < 2 else .98)
                elif style == "grid":
                    seam = x % 16 < 2 or y % 16 < 2
                    shade = .68 if seam else (.88 if ((x//16+y//16)%3==0) else .99)
                else:
                    seam = x % 20 < 2 or y % 20 < 2
                    shade = .70 if seam else (.94 if ((x//20+y//20)%2==0) else 1.0)
                noise = rng.uniform(-.035,.035)
                value=max(0,min(1,shade+noise))
                image.setXel(x,y,value,value,value)
        texture=Texture(name)
        texture.load(image)
        texture.setWrapU(Texture.WMRepeat)
        texture.setWrapV(Texture.WMRepeat)
        texture.setMinfilter(Texture.FTLinearMipmapLinear)
        texture.setMagfilter(Texture.FTLinear)
        return texture

    def _mesh_batch(self, name, boxes, color):
        """Combine many simple boxes into one GeomNode to limit draw calls."""
        data = GeomVertexData(name, GeomVertexFormat.getV3t2(), Geom.UHStatic)
        writer = GeomVertexWriter(data, "vertex")
        tex_writer = GeomVertexWriter(data, "texcoord")
        tris = GeomTriangles(Geom.UHStatic)
        for (x, y, z), (sx, sy, sz) in boxes:
            for face in _CUBE_FACES:
                first=writer.getWriteRow()
                for vertex_index in face:
                    vx,vy,vz=_CUBE_VERTS[vertex_index]
                    writer.addData3(x+vx*sx,y+vy*sy,z+vz*sz)
                    if len(set(face)) == 4 and all(_CUBE_VERTS[i][2] == _CUBE_VERTS[face[0]][2] for i in face):
                        uv=(vx*sx/3.0,vy*sy/3.0)
                    elif all(_CUBE_VERTS[i][1] == _CUBE_VERTS[face[0]][1] for i in face):
                        uv=(vx*sx/3.0,vz*sz/3.0)
                    else:
                        uv=(vy*sy/3.0,vz*sz/3.0)
                    tex_writer.addData2(*uv)
                tris.addVertices(first,first+1,first+2)
                tris.addVertices(first,first+2,first+3)
        geom = Geom(data)
        geom.addPrimitive(tris)
        node = GeomNode(name)
        node.addGeom(geom)
        path = self.render.attachNewNode(node)
        path.setColor(*color)
        return path

    def _mesh_cylinders(self,name,cylinders,color,sides=10):
        data=GeomVertexData(name,GeomVertexFormat.getV3(),Geom.UHStatic)
        writer=GeomVertexWriter(data,"vertex")
        triangles=GeomTriangles(Geom.UHStatic)
        for x,y,z,radius,height in cylinders:
            first=writer.getWriteRow()
            for ring_z in (z-height/2,z+height/2):
                for side in range(sides):
                    angle=2*math.pi*side/sides
                    writer.addData3(x+math.cos(angle)*radius,y+math.sin(angle)*radius,ring_z)
            bottom_center=writer.getWriteRow(); writer.addData3(x,y,z-height/2)
            top_center=writer.getWriteRow(); writer.addData3(x,y,z+height/2)
            for side in range(sides):
                nxt=(side+1)%sides
                triangles.addVertices(first+side,first+nxt,first+sides+nxt)
                triangles.addVertices(first+side,first+sides+nxt,first+sides+side)
                triangles.addVertices(bottom_center,first+nxt,first+side)
                triangles.addVertices(top_center,first+sides+side,first+sides+nxt)
        geom=Geom(data); geom.addPrimitive(triangles); node=GeomNode(name); node.addGeom(geom)
        path=self.render.attachNewNode(node); path.setColor(*color)
        return path

    def _mesh_gable_roofs(self,name,roofs,color):
        """Batch pitched roofs so the residential district reads as houses."""
        data=GeomVertexData(name,GeomVertexFormat.getV3(),Geom.UHStatic)
        writer=GeomVertexWriter(data,"vertex")
        triangles=GeomTriangles(Geom.UHStatic)
        for x,y,z,width,depth,rise in roofs:
            base=[(x-width/2,y-depth/2,z),(x+width/2,y-depth/2,z),
                  (x+width/2,y+depth/2,z),(x-width/2,y+depth/2,z)]
            ridge=[(x,y-depth/2,z+rise),(x,y+depth/2,z+rise)]
            first=writer.getWriteRow()
            for vertex in (*base,*ridge): writer.addData3(*vertex)
            triangles.addVertices(first,first+4,first+5)
            triangles.addVertices(first,first+5,first+3)
            triangles.addVertices(first+1,first+2,first+5)
            triangles.addVertices(first+1,first+5,first+4)
            triangles.addVertices(first,first+1,first+4)
            triangles.addVertices(first+2,first+3,first+5)
        geom=Geom(data); geom.addPrimitive(triangles)
        node=GeomNode(name); node.addGeom(geom)
        path=self.render.attachNewNode(node); path.setColor(*color); path.setLightOff()
        return path

    def _asset_box(self, name, pos, scale, color, layer=None):
        """Create a selectable, named utility asset with simple readable parts."""
        data = GeomVertexData(name, GeomVertexFormat.getV3(), Geom.UHStatic)
        writer = GeomVertexWriter(data, "vertex")
        for vertex in _CUBE_VERTS:
            writer.addData3(*vertex)
        triangles = GeomTriangles(Geom.UHStatic)
        for a, b, c in _CUBE_TRIS:
            triangles.addVertices(a, b, c)
        geom = Geom(data)
        geom.addPrimitive(triangles)
        geom_node = GeomNode(name)
        geom_node.addGeom(geom)
        path = self.render.attachNewNode(geom_node)
        path.setName(name)
        path.setPos(*pos)
        path.setScale(*scale)
        path.setColor(*color)
        path.setPythonTag("asset_id", name)
        solid = CollisionNode(f"pick-{name}")
        solid.addSolid(CollisionBox((0, 0, 0), .5, .5, .5))
        solid.setIntoCollideMask(BitMask32.bit(1))
        solid.setFromCollideMask(BitMask32.allOff())
        path.attachNewNode(solid)
        self._assets[name] = path
        if layer:
            self.layers[layer].append(path)
        return path

    def _build_city(self, cfg):
        rng = random.Random(20261020)
        zones = cfg["zones"]
        centers = CITY_CENTERS
        self._zone_centers = centers

        # Quiet ground and a continuous asphalt grid replace the opaque colored slabs.
        self._mesh_batch("city-ground", [((0, 0, -1.1), (140, 140, 1))], (.17, .21, .20, 1))
        road_boxes = []
        sidewalk_boxes = []
        curb_boxes = []
        marking_boxes = []
        for coordinate in ARTERIAL_CENTERS:
            road_boxes.extend([((coordinate, 0, -.12), (ARTERIAL_WIDTH, 140, .12)), ((0, coordinate, -.12), (140, ARTERIAL_WIDTH, .12))])
            sidewalk_boxes.extend([
                ((coordinate-ARTERIAL_SIDEWALK_OFFSET,0,-.06),(ARTERIAL_SIDEWALK_WIDTH,140,.12)), ((coordinate+ARTERIAL_SIDEWALK_OFFSET,0,-.06),(ARTERIAL_SIDEWALK_WIDTH,140,.12)),
                ((0,coordinate-ARTERIAL_SIDEWALK_OFFSET,-.06),(140,ARTERIAL_SIDEWALK_WIDTH,.12)), ((0,coordinate+ARTERIAL_SIDEWALK_OFFSET,-.06),(140,ARTERIAL_SIDEWALK_WIDTH,.12)),
            ])
            # Low curbs sharpen the road edge without adding individual objects.
            curb_boxes.extend([
                    ((coordinate-ARTERIAL_CURB_OFFSET,0,-.025),(.38,140,.12)),
                    ((coordinate+ARTERIAL_CURB_OFFSET,0,-.025),(.38,140,.12)),
                    ((0,coordinate-ARTERIAL_CURB_OFFSET,-.025),(140,.38,.12)),
                    ((0,coordinate+ARTERIAL_CURB_OFFSET,-.025),(140,.38,.12)),
            ])
            for tick in range(-60, 65, 8):
                marking_boxes.extend([
                    ((coordinate,tick,-.045),(.16,3.2,.035)),
                    ((tick,coordinate,-.045),(3.2,.16,.035)),
                ])
        intersections = sorted({
            (cx + dx*20, cy + dy*20)
            for cx, cy in centers.values()
            for dx in (-1,1) for dy in (-1,1)
        })
        intersection_marks = []
        for ix, iy in intersections:
            # Stop lines sit five metres before the junction on every approach.
            for direction in (-1,1):
                intersection_marks.extend([
                    ((ix+direction*5,iy,-.045),(.22,7.2,.035)),
                    ((ix,iy+direction*5,-.045),(7.2,.22,.035)),
                ])
            # Simple zebra crossings make the junction and its stop lines clear.
            for direction in (-1,1):
                for stripe in (-3.15,-2.25,-1.35,-.45,.45,1.35,2.25,3.15):
                    intersection_marks.extend([
                        ((ix+direction*4.25,iy+stripe,-.045),(.46,.82,.035)),
                        ((ix+stripe,iy+direction*4.25,-.045),(.82,.46,.035)),
                    ])
        # Each district has a small cross street that connects its buildings
        # directly to the surrounding road grid.
        for cx, cy in centers.values():
            road_boxes.extend([
                ((cx,cy,-.12),(LOCAL_WIDTH,24,.12)),
                ((cx,cy,-.12),(24,LOCAL_WIDTH,.12)),
            ])
            sidewalk_boxes.extend([
                ((cx-LOCAL_SIDEWALK_OFFSET,cy,-.055),(LOCAL_SIDEWALK_WIDTH,24,.08)),
                ((cx+LOCAL_SIDEWALK_OFFSET,cy,-.055),(LOCAL_SIDEWALK_WIDTH,24,.08)),
                ((cx,cy-LOCAL_SIDEWALK_OFFSET,-.055),(24,LOCAL_SIDEWALK_WIDTH,.08)),
                ((cx,cy+LOCAL_SIDEWALK_OFFSET,-.055),(24,LOCAL_SIDEWALK_WIDTH,.08)),
            ])
        asphalt = self._mesh_batch("asphalt-roads", road_boxes, (.105,.125,.14,1))
        asphalt.setTexture(self._make_grain_texture("procedural-asphalt",(.105,.12,.13),.025,41),1)
        concrete = self._mesh_batch("concrete-sidewalks", sidewalk_boxes, (.52,.52,.48,1))
        concrete.setTexture(self._make_grain_texture("procedural-concrete",(.47,.47,.43),.065,71),1)
        self._mesh_batch("sidewalk-curbs", curb_boxes, (.59,.56,.48,1))
        self._mesh_batch("road-lane-dashes", marking_boxes, (.77,.72,.54,1))
        self._mesh_batch("intersection-crosswalks-and-stop-lines", intersection_marks, (.9,.9,.82,1))

        wall_boxes = {z: [[],[],[]] for z in "ABCD"}
        roof_boxes = {z: [] for z in "ABCD"}
        gable_roofs = {z: [] for z in "ABCD"}
        roof_detail_boxes = {z: [[],[],[]] for z in "ABCD"}
        window_boxes = {z: [[],[]] for z in "ABCD"}
        trim_boxes = {z: [] for z in "ABCD"}
        balcony_boxes = {z: [] for z in "ABCD"}
        entrance_boxes = []
        residential_planters = []
        residential_paths = []
        shopfront_glass = []
        shopfront_frames = []
        shop_signs = []
        loading_door_boxes = []
        factory_chimneys = []
        factory_silos = []
        tree_trunks = []
        tree_crowns = [[],[],[]]
        building_records = []
        zone_label_positions = []
        wall_palettes = {}
        roof_palettes = {}

        for zone in zones:
            zid = zone["id"]
            cx, cy = centers[zid]
            # Subtle district paving and a fine border identify districts without hiding streets.
            self._mesh_batch(f"district-{zid}", [((cx,cy,-.39),(DISTRICT_SIZE,DISTRICT_SIZE,.05))], (.22,.255,.245,1))
            profile = {
                "A": ((MAX_BUILDING_FOOTPRINT,2.55),(4.2,8.0)),
                "B": ((MAX_BUILDING_FOOTPRINT,MAX_BUILDING_FOOTPRINT),(10,23)),
                "C": ((MAX_BUILDING_FOOTPRINT,MAX_BUILDING_FOOTPRINT),(4.8,8.5)),
                "D": ((MAX_BUILDING_FOOTPRINT,2.55),(8,19)),
            }[zid]
            footprint, height_range = profile
            building_positions = building_lots(zone["buildings"])
            wall_palette = {
                "A": [(.67,.52,.40,1),(.73,.62,.48,1),(.52,.59,.49,1)],
                "B": [(.41,.55,.63,1),(.65,.54,.41,1),(.52,.60,.65,1)],
                "C": [(.58,.47,.38,1),(.66,.59,.43,1),(.46,.54,.48,1)],
                "D": [(.50,.66,.70,1),(.63,.66,.63,1),(.43,.54,.62,1)],
            }[zid]
            wall_palettes[zid] = wall_palette
            roof_base = {"A":(.34,.27,.23,1),"B":(.32,.38,.42,1),
                         "C":(.29,.32,.31,1),"D":(.38,.43,.44,1)}[zid]
            roof_palettes[zid] = [
                roof_base,
                tuple(min(1.0,c*1.12) for c in roof_base[:3])+(1,),
                tuple(max(0.0,c*.86) for c in roof_base[:3])+(1,),
            ]
            # Each district occupies the block between the four main roads.
            # Keep a clear cross-shaped local street and place buildings inside
            # the four resulting lots instead of over the road grid.
            for i, (lot_x, lot_y) in enumerate(building_positions):
                bx, by = cx + lot_x, cy + lot_y
                height = rng.uniform(*height_range)
                sx = footprint[0] * rng.uniform(.84,.98)
                sy = footprint[1] * rng.uniform(.84,.98)
                if zid == "C" and i % 3 == 0:
                    height = rng.uniform(4.5,6.5)
                    if i % 6 == 0:
                        factory_chimneys.append((bx-sx*.22,by+sy*.2,height+2.8,.42,5.6))
                        factory_silos.append((bx+sx*.2,by-sy*.2,height+1.8,.72,3.6))
                variant=i%3
                wall_boxes[zid][variant].append(((bx,by,height/2),(sx,sy,height)))
                if zid=="A":
                    gable_roofs[zid].append((bx,by,height,sx+.22,sy+.22,1.0))
                    front_y=by-sy/2-.075
                    entrance_boxes.append(((bx,front_y,1.05),(.72,.13,1.85)))
                    if i%3==0:
                        entrance_boxes.append(((bx+sx*.27,front_y,1.0),(1.05,.14,1.5)))
                    # Small paired planters and a path make house fronts legible.
                    for side in (-1,1):
                        residential_planters.extend([
                            ((bx+side*sx*.34,front_y-.42,.25),(.43,.55,.48)),
                            ((bx+side*sx*.34,front_y-.43,.56),(.31,.38,.18)),
                        ])
                    residential_paths.append(((bx,front_y-1.25,.035),(.62,1.45,.07)))
                else:
                    roof_boxes[zid].append(((bx,by,height+.18),(sx+.14,sy+.14,.32)))
                if zid=="B":
                    front_y=by-sy/2-.065
                    shopfront_glass.append(((bx,front_y,1.5),(sx*.72,.12,1.75)))
                    shopfront_frames.extend([
                        ((bx-sx*.39,front_y-.02,1.5),(.11,.15,1.95)),
                        ((bx+sx*.39,front_y-.02,1.5),(.11,.15,1.95)),
                        ((bx,front_y-.03,.68),(sx*.82,.16,.13)),
                        ((bx,front_y-.03,2.42),(sx*.82,.16,.13)),
                    ])
                    shop_signs.append(((bx,front_y-.11,2.78),(sx*.79,.16,.46)))
                # Repeated facade bays and floor bands make building use and scale legible.
                floors = max(1, int(height/3.1))
                windows_per_side = 2 if sx < 6.5 else 3
                for floor in range(floors):
                    wz = 1.25 + floor*3.05
                    if wz > height-.55:
                        continue
                    for pane in range(windows_per_side):
                        wx = bx + (pane-(windows_per_side-1)/2)*(sx/(windows_per_side+.2))
                        wy = by + (pane-(windows_per_side-1)/2)*(sy/(windows_per_side+.2))
                        lit_window=(i+floor+pane)%5==0
                        window_boxes[zid][int(lit_window)].extend([
                            ((wx,by-sy/2-.045,wz),(.90,.09,1.15)),
                            ((wx,by+sy/2+.045,wz),(.90,.09,1.15)),
                            ((bx-sx/2-.045,wy,wz),(.09,.90,1.15)),
                            ((bx+sx/2+.045,wy,wz),(.09,.90,1.15)),
                        ])
                    trim_boxes[zid].append(((bx,by-sy/2-.05,wz-.62),(sx-.3,.08,.09)))
                    if zid=="D" and floor>0:
                        for side in (-1,1):
                            balcony_boxes[zid].extend([
                                ((bx,by+side*(sy/2+.12),wz-.52),(sx*.88,.24,.11)),
                                ((bx,by+side*(sy/2+.23),wz-.30),(sx*.82,.055,.24)),
                            ])
                if zid=="C" and i%2==0:
                    loading_door_boxes.append(((bx,by-sy/2-.055,1.25),(sx*.58,.11,1.8)))
                # Rooftop plant boxes and a parapet/cap vary the skyline.
                if zid!="A" and i % 2 == 0:
                    roof_detail_boxes[zid][variant].append(
                        ((bx+sx*.2,by,height+.63),(sx*.28,sy*.25,.48)))
                building_records.append((zid,i,bx,by,height,sx,sy))

            # Trees along sidewalks and small green pockets, not through building plots.
            for i, offset in enumerate((-24,-12,0,12,24)):
                for tx, ty in ((cx-27,cy+offset),(cx+27,cy+offset),(cx+offset,cy-27),(cx+offset,cy+27)):
                    if (i+ord(zid))%2 == 0:
                        tree_trunks.append(((tx,ty,1.0),(.42,.42,2.0)))
                        variant=(i+ord(zid))%3
                        tree_crowns[variant].extend([((tx,ty,2.6),(2.0,2.0,2.4)),((tx,ty,3.7),(1.35,1.35,1.5))])
            zone_label_positions.append((zid, zone["name"], cx, cy))

        facade_styles={"A":"brick","B":"grid","C":"metal","D":"panel"}
        facade_textures={zid:self._make_facade_texture(
            f"facade-{zid}-procedural",facade_styles[zid],400+ord(zid)) for zid in "ABCD"}
        for zid in "ABCD":
            for variant in range(3):
                walls=self._mesh_batch(f"buildings-{zid}-variant-{variant+1}",
                                       wall_boxes[zid][variant],wall_palettes[zid][variant])
                walls.setTexture(facade_textures[zid],1)
                detail=self._mesh_batch(f"rooftop-details-{zid}-variant-{variant+1}",
                                        roof_detail_boxes[zid][variant],roof_palettes[zid][variant])
                self._quality_nodes.append(detail)
            if zid=="A":
                self._mesh_gable_roofs(f"residential-pitched-roofs-{zid}",gable_roofs[zid],(.36,.29,.24,1))
            else:
                self._mesh_batch(f"rooftops-{zid}",roof_boxes[zid],roof_palettes[zid][0])
            dark_windows=self._mesh_batch(f"windows-dark-{zid}",window_boxes[zid][0],(.04,.10,.14,1))
            lit_windows=self._mesh_batch(f"windows-lit-{zid}",window_boxes[zid][1],(.74,.49,.25,1))
            dark_windows.setLightOff()
            lit_windows.setLightOff()
            self._lit_window_nodes.append(lit_windows)
            trim=self._mesh_batch(f"floor-trims-{zid}", trim_boxes[zid], (.78,.73,.62,1))
            self._quality_nodes.append(trim)
            if balcony_boxes[zid]:
                balcony=self._mesh_batch(f"balconies-{zid}",balcony_boxes[zid],(.56,.59,.58,1))
                self._quality_nodes.append(balcony)
        self._mesh_batch("industrial-loading-doors",loading_door_boxes,(.15,.19,.21,1))
        self._mesh_batch("building-entrances-and-garages",entrance_boxes,(.24,.16,.11,1))
        planters=self._mesh_batch("residential-planters",residential_planters,(.18,.36,.22,1))
        planters.setLightOff()
        self._quality_nodes.append(planters)
        paths=self._mesh_batch("residential-front-walkways",residential_paths,(.52,.49,.42,1))
        self._mesh_batch("commercial-storefront-glass",shopfront_glass,(.10,.29,.36,1))
        self._mesh_batch("commercial-storefront-frames",shopfront_frames,(.16,.20,.22,1))
        signs=self._mesh_batch("commercial-shop-signs",shop_signs,(.91,.58,.20,1))
        self._quality_nodes.append(signs)
        self._mesh_batch("street-tree-trunks",tree_trunks,(.29,.22,.15,1))
        for variant,color in enumerate(((.09,.28,.19,1),(.12,.34,.23,1),(.16,.32,.19,1))):
            self._mesh_batch(f"street-tree-crowns-variant-{variant+1}",tree_crowns[variant],color)
        self._mesh_cylinders("factory-chimneys",factory_chimneys,(.62,.29,.2,1))
        self._mesh_cylinders("factory-silos",factory_silos,(.56,.62,.59,1))

        # Utility assets are separated from buildings and grouped by the layer keys.
        for zid, (cx, cy) in centers.items():
            self._asset_box(f"TX-{zid}-01",(cx-18,cy-18,1.0),(2.7,2.2,2.0),(.82,.62,.27,1),"electrical")
            self._asset_box(f"OLT-{zid}-01",(cx+18,cy-18,1.25),(2.0,1.6,2.5),(.22,.61,.68,1),"gpon")
            for idx in range(4):
                lx, ly = cx-18+idx*12, cy-20.8
                self._asset_box(f"LAMP-{zid}-{idx}",(lx,ly,2.6),(.16,.16,5.2),(.30,.32,.31,1),"electrical")
                self._asset_box(f"LAMP-HEAD-{zid}-{idx}",(lx+.65,ly,5.1),(1.5,.42,.18),(.86,.75,.43,1),"electrical")
                self._asset_box(f"GPON-NAP-{zid}-{idx+1:02d}",(lx-.12,ly,4.35),(.66,.42,.58),(.91,.12,.18,1),"gpon")
                self._asset_box(f"GPON-ARM-{zid}-{idx+1:02d}",(lx-.10,ly,4.72),(.12,.12,.55),(.48,.49,.48,1),"gpon")
            # Warm lamp bulbs read clearly while keeping just one sun and one ambient light.
            for idx in (1,3):
                lx,ly=cx-18+idx*12,cy-20.8
                bulb=self._asset_box(f"LAMP-BULB-{zid}-{idx}",(lx+.65,ly,5.05),(.44,.44,.22),(1.0,.72,.32,1),"electrical")
                bulb.setLightOff()
                bulb.setColorScale(1.15,1.0,.72,1)
                self.layers["electrical"].append(bulb)
                self._lamp_bulbs.append(bulb)

        self._build_traffic_signals(intersections)
        self._build_network_layers(centers)
        self._build_cars(centers)
        self._build_pedestrians(centers)

        self._build_landmarks(building_records)
        for zid, name, x, y in zone_label_positions:
            self._world_label(f"ZONA {zid} | {name.upper()}",(x,y+28,27),(.83,.9,.84,1),15)

    @staticmethod
    def _unit_sphere_geom(name, rings=8, sectors=12):
        """Small smooth sphere mesh for signal lenses and their glow."""
        data=GeomVertexData(name,GeomVertexFormat.getV3n3(),Geom.UHStatic)
        vertex=GeomVertexWriter(data,"vertex")
        normal=GeomVertexWriter(data,"normal")
        for ring in range(rings+1):
            latitude=math.pi*ring/rings
            z=math.cos(latitude)
            radius=math.sin(latitude)
            for sector in range(sectors+1):
                longitude=2*math.pi*sector/sectors
                x=radius*math.cos(longitude)
                y=radius*math.sin(longitude)
                vertex.addData3(x,y,z)
                normal.addData3(x,y,z)
        triangles=GeomTriangles(Geom.UHStatic)
        stride=sectors+1
        for ring in range(rings):
            for sector in range(sectors):
                a=ring*stride+sector
                b=a+stride
                triangles.addVertices(a,b,a+1)
                triangles.addVertices(a+1,b,b+1)
        geom=Geom(data)
        geom.addPrimitive(triangles)
        return geom

    def _build_traffic_signals(self, intersections):
        pole_boxes, housing_boxes = [], []
        lens_colors = ((.95,.12,.08,1),(.98,.62,.08,1),(.12,.9,.26,1))
        bulb_geom=self._unit_sphere_geom("traffic-signal-bulb")
        glow_geom=self._unit_sphere_geom("traffic-signal-glow",6,10)
        for ix, iy in intersections:
            groups = {"horizontal": [], "vertical": []}
            for dx, dy in ((-1,-1),(-1,1),(1,-1),(1,1)):
                x, y = ix+dx*5.2, iy+dy*5.2
                axis = "horizontal" if dx == dy else "vertical"
                pole_boxes.append(((x,y,2.15),(.2,.2,4.3)))
                housing_boxes.append(((x,y,4.95),(.66,.48,1.55)))
                lenses, halos = [], []
                for index, (z,color) in enumerate(zip((5.38,4.94,4.5),lens_colors)):
                    lens_node=GeomNode(f"signal-{ix}-{iy}-{dx}-{dy}-{index}")
                    lens_node.addGeom(bulb_geom)
                    lens=self.render.attachNewNode(lens_node)
                    lens.setPos(x,y,z)
                    lens.setScale(.17,.14,.17)
                    lens.setColor(*color)
                    lens.setLightOff()
                    lenses.append(lens)
                    halo_node=GeomNode(f"signal-glow-{ix}-{iy}-{dx}-{dy}-{index}")
                    halo_node.addGeom(glow_geom)
                    halo=self.render.attachNewNode(halo_node)
                    halo.setPos(x,y,z)
                    halo.setScale(.38,.30,.38)
                    halo.setColor(color[0],color[1],color[2],.24)
                    halo.setLightOff()
                    halo.setTransparency(TransparencyAttrib.MAlpha)
                    halo.setDepthWrite(False)
                    halo.hide()
                    halos.append(halo)
                signal = {"axis":axis,"lenses":lenses,"halos":halos,"colors":lens_colors}
                groups[axis].append(signal)
                self._traffic_signals.append(signal)
            self._intersection_signals[(ix,iy)] = groups
        self._mesh_batch("traffic-signal-poles",pole_boxes,(.19,.21,.21,1))
        self._mesh_batch("traffic-signal-housings",housing_boxes,(.11,.13,.14,1))

    @staticmethod
    def _signal_state(axis, simulation_time):
        phase = simulation_time % 20.0
        if axis == "horizontal":
            if phase < 7.0:
                return "green"
            if phase < 9.0:
                return "yellow"
            return "red"
        if phase < 10.0:
            return "red"
        if phase < 17.0:
            return "green"
        if phase < 19.0:
            return "yellow"
        return "red"

    def _build_landmarks(self, records):
        # Add recognizable civic/industrial forms to prevent four interchangeable blocks.
        for zid, index, x, y, height, sx, sy in records:
            if zid == "D" and index == 0:
                self._asset_box("HOSPITAL-D-01",(x,y,height+1),(sx*.75,sy*.75,2),(.83,.82,.73,1))
                self._world_label("HOSPITAL",(x,y,height+2.5),(1,.88,.68,1),9)
            elif zid == "D" and index == 1:
                self._asset_box("NOC-D-01",(x,y,height+1),(sx*.72,sy*.72,2),(.23,.49,.58,1))
                self._world_label("NOC / DATA",(x,y,height+2.5),(.61,.9,.93,1),9)
            elif zid == "C" and index in (2,8,14):
                # A small stack distinguishes the industrial skyline.
                self._asset_box(f"STACK-C-{index}",(x+sx*.3,y,height+3),(.85,.85,6),(.48,.45,.39,1))

    def _world_label(self, text, pos, color, size=10):
        node = TextNode(f"label-{text}")
        node.setText(text)
        node.setAlign(TextNode.ACenter)
        node.setTextColor(*color)
        node.setCardColor(0.025,0.04,0.05,.72)
        node.setCardAsMargin(.3,.3,.12,.12)
        node.setCardDecal(True)
        label = self.render.attachNewNode(node)
        label.setPos(*pos)
        label.setScale(size/100)
        label.setBillboardPointEye()
        return label

    def _control_button_textures(self, aspect, active=False):
        aspect = min(8.0, max(1.0, round(aspect * 2) / 2))
        key = (aspect, bool(active))
        if key not in self._button_texture_cache:
            if active:
                fills = ((.17,.88,.95,1),(.02,.61,.76,1),(.38,.95,.99,1),(.50,.59,.61,1))
            else:
                fills = ((.015,.70,.90,1),(.00,.52,.70,1),(.20,.83,.96,1),(.50,.59,.61,1))
            outline = (.94,.10,.16,1)
            self._button_texture_cache[key] = tuple(
                self._make_button_texture(f"control-{key}-{index}",aspect,fill,outline)
                for index,fill in enumerate(fills)
            )
        return self._button_texture_cache[key]

    def _style_control_button(self, button, active=False):
        left,right,bottom,top = button["frameSize"]
        aspect = (right-left) / max(top-bottom,1e-6)
        button["frameTexture"] = self._control_button_textures(aspect,active)
        button["frameColor"] = (1,1,1,1)
        button["relief"] = "flat"
        button["borderWidth"] = (0,0)
        button["text_fg"] = (.012,.045,.062,1)
        button["text_scale"] = getattr(button,"control_text_scale",.90)
        if self._button_font:
            button["text_font"] = self._button_font
        button.setTransparency(TransparencyAttrib.MAlpha)

    def _make_hud(self):
        self._button_texture_cache = {}
        bold_font_path = Path("C:/Windows/Fonts/arialbd.ttf")
        self._button_font = None
        if bold_font_path.exists():
            try:
                panda_font_path = Filename.fromOsSpecific(str(bold_font_path)).getFullpath()
                self._button_font = self.loader.loadFont(panda_font_path)
            except OSError:
                self._button_font = None
        self._hud_header_frame = DirectFrame(
            frameColor=(.012,.032,.048,.99),
            frameSize=(-1.68,1.68,-.142,.142), pos=(0,0,.862), relief=1,
        )
        self._hud_header_frame.setTransparency(TransparencyAttrib.MAlpha)
        self._hud_title = OnscreenText(
            text="JONGOX  |  GEMELO DIGITAL URBANO",
            pos=(-1.55,.95), align=TextNode.ALeft, scale=.047,
            fg=(.88,.93,.9,1), mayChange=False, shadow=(0,0,0,.7),
        )
        self._hud_help = OnscreenText(
            text="Clic derecho: orbitar | rueda: acercar/alejar | clic central: desplazar\n"
                 "Flechas/WASD: mover | Q/E: girar | +/-: zoom | 1/2: capas | R: inicio",
            pos=(-1.55,.875), align=TextNode.ALeft, scale=.025,
            fg=(.65,.77,.78,1), mayChange=False, shadow=(0,0,0,.7),
        )
        self._hud_zones = OnscreenText(
            text="A  RESIDENCIAL\nB  COMERCIAL\nC  INDUSTRIAL\nD  TECNOL\u00d3GICA",
            pos=(1.55,.92), align=TextNode.ARight, scale=.026,
            fg=(.93,.96,.93,1), mayChange=False, shadow=(0,0,0,.7),
        )
        self._hud_control_frame = DirectFrame(
            frameColor=(.012,.032,.048,.985), frameSize=(-1.68,1.68,-.12,.12),
            pos=(0,0,.61), relief=1,
        )
        self._hud_control_frame.setTransparency(TransparencyAttrib.MAlpha)
        self._hud_control_cards = [
            DirectFrame(frameColor=(.025,.063,.079,.99),
                        frameSize=(-.59,.59,-.097,.085),pos=(-1.02,0,.61),relief=1),
            DirectFrame(frameColor=(.025,.063,.079,.99),
                        frameSize=(-.47,.47,-.097,.085),pos=(.105,0,.61),relief=1),
            DirectFrame(frameColor=(.025,.063,.079,.99),
                        frameSize=(-.51,.51,-.097,.085),pos=(1.145,0,.61),relief=1),
        ]
        self._hud_control_rules = [
            DirectFrame(frameColor=(.16,.39,.43,.95), frameSize=(-.002,.002,-.10,.10),
                        pos=(-.39,0,.61), relief=0),
            DirectFrame(frameColor=(.16,.39,.43,.95), frameSize=(-.002,.002,-.10,.10),
                        pos=(.63,0,.61), relief=0),
            DirectFrame(frameColor=(.10,.72,.68,1), frameSize=(-1.7,1.7,-.003,.003),
                        pos=(0,0,.49), relief=0),
        ]
        self._hud_control_labels = [
            OnscreenText(text="01  /  SIMULACI\u00d3N", pos=(-1.02,.685), align=TextNode.ACenter,
                         scale=.024, fg=(.55,.88,.89,1), mayChange=False),
            OnscreenText(text="02  /  ILUMINACI\u00d3N", pos=(.105,.685), align=TextNode.ACenter,
                         scale=.024, fg=(.55,.88,.89,1), mayChange=False),
            OnscreenText(text="03  /  SECTORES", pos=(1.145,.685), align=TextNode.ACenter,
                         scale=.024, fg=(.55,.88,.89,1), mayChange=False),
        ]
        self._layer_buttons["electrical"] = DirectButton(
            text="RED EL\u00c9CTRICA", scale=.027, pos=(1.28,0,-.78),
            command=self._toggle_layer, extraArgs=["electrical"],
            frameSize=(-10.4,.12,-.7,.7), frameColor=(.035,.07,.10,.72),
            text_align=TextNode.ARight, text_fg=(.22,.62,1,1), pressEffect=True,
        )
        self._layer_buttons["gpon"] = DirectButton(
            text="RED GPON", scale=.027, pos=(1.28,0,-.85),
            command=self._toggle_layer, extraArgs=["gpon"],
            frameSize=(-5.0,.12,-.7,.7), frameColor=(.035,.07,.10,.72),
            text_align=TextNode.ARight, text_fg=(1,.28,.32,1), pressEffect=True,
        )
        self._hud_selection = OnscreenText(
            text="Activo seleccionado: ninguno",
            pos=(-1.29,-.94), align=TextNode.ALeft, scale=.032,
            fg=(.95,.78,.38,1), mayChange=True, shadow=(0,0,0,.7),
        )
        self._hud_quality = OnscreenText(
            text="CALIDAD GR\u00c1FICA", pos=(-1.55,.80), align=TextNode.ALeft,
            scale=.026, fg=(.82,.89,.84,1), mayChange=False,
        )
        self._hud_time = OnscreenText(
            text="ILUMINACI\u00d3N: D\u00cdA", pos=(.30,.80), align=TextNode.ALeft,
            scale=.024, fg=(.87,.91,.82,1), mayChange=True,
            shadow=(0,0,0,.7),
        )
        self._quality_buttons["LOW"] = DirectButton(
            text="BAJA", scale=.055, pos=(-.76,0,.80), command=self._set_quality,
            extraArgs=["LOW"], frameSize=(-1.4,1.4,-.55,.55),
            frameColor=(.06,.17,.21,1), text_fg=(.94,.97,.96,1), pressEffect=True,
        )
        self._quality_buttons["MEDIUM"] = DirectButton(
            text="MEDIA", scale=.055, pos=(-.47,0,.80), command=self._set_quality,
            extraArgs=["MEDIUM"], frameSize=(-1.4,1.4,-.55,.55),
            frameColor=(.06,.17,.21,1), text_fg=(.94,.97,.96,1), pressEffect=True,
        )
        control_style={"frameColor":(.06,.17,.21,.99),
                       "text_fg":(.94,.97,.96,1), "pressEffect":True}
        self._pause_button=DirectButton(
            text="PAUSAR", pos=(-1.20,0,.565), command=self._toggle_pause,
            frameSize=(-2.15,2.15,-.82,.82), frameColor=(.06,.48,.44,1),
            text_fg=(1,.99,.9,1), scale=.045, pressEffect=True,
        )
        self._restart_button=DirectButton(
            text="REINICIAR", pos=(-.77,0,.565), command=self._reset_simulation,
            frameSize=(-2.6,2.6,-.82,.82), scale=.045, **control_style)
        self._restart_button.control_text_scale=.76
        for mode,label,x,width in (("AUTO","AUTOM\u00c1TICO",-.22,2.85),
                                   ("DAY","D\u00cdA",.00,1.25),
                                   ("AFTERNOON","TARDE",.22,1.65),
                                   ("NIGHT","NOCHE",.44,1.65)):
            self._time_buttons[mode]=DirectButton(
                text=label, pos=(x,0,.565), command=self._set_time_of_day,
                extraArgs=[mode], frameSize=(-width,width,-.82,.82), scale=.034,
                **control_style)
        self._time_buttons["AUTO"].control_text_scale=.76
        for zone,x in (("A",.74),("B",.93),("C",1.12),("D",1.31)):
            self._zone_buttons[zone]=DirectButton(
                text=zone, scale=.031, pos=(x,0,.565), command=self._focus_zone,
                extraArgs=[zone], frameSize=(-.78,.78,-.7,.7),
                frameColor=(.06,.17,.21,.99), text_fg=(.94,.97,.96,1), pressEffect=True,
            )
        self._help_button = DirectButton(
            text="AYUDA", scale=.024, pos=(1.49,0,.565), command=self._toggle_help,
            frameSize=(-2.0,2.0,-.8,.8), frameColor=(.08,.25,.32,1),
            text_fg=(.62,.86,1,1), pressEffect=True,
        )
        self._help_frame = DirectFrame(
            frameColor=(.018,.035,.048,.96), frameSize=(-.42,.42,-.24,.24),
            pos=(-.87,0,-.62), relief=1,
        )
        self._help_frame.setTransparency(TransparencyAttrib.MAlpha)
        self._help_text = OnscreenText(
            text=("AYUDA DEL SIMULADOR\nFlechas/WASD: mover c\u00e1mara\nQ/E: girar | +/-: acercar/alejar\n"
                  "Clic derecho: orbitar | central: desplazar\nPAUSAR detiene autos y sem\u00e1foros\n"
                  "D\u00cdA/TARDE/NOCHE cambia la luz\nA-D enfoca una zona\n"
                  "Capas: red el\u00e9ctrica y GPON\nR: volver al inicio"),
            pos=(-1.25,-.43), align=TextNode.ALeft, scale=.019,
            fg=(.84,.91,.92,1), mayChange=False, shadow=(0,0,0,.8),
        )
        self._help_frame.hide()
        self._help_text.hide()
        self._hud_perf = OnscreenText(
            text="FPS --  |  MEMORIA -- MB", pos=(1.28,-.94), align=TextNode.ARight,
            scale=.026, fg=(.56,.83,.78,1), mayChange=True, shadow=(0,0,0,.7),
        )
        all_buttons=(
            list(self._layer_buttons.values())+list(self._quality_buttons.values())
            +[self._pause_button,self._restart_button,self._help_button]
            +list(self._time_buttons.values())+list(self._zone_buttons.values())
        )
        for button in all_buttons:
            self._style_control_button(button)
        self._set_quality(self._quality_mode)
        for mode,button in self._time_buttons.items():
            self._style_control_button(button,active=(mode=="AUTO"))
        for label,button in self._zone_buttons.items():
            self._style_control_button(button,active=(label==self._active_zone))
        for name,button in self._layer_buttons.items():
            self._style_control_button(button,active=self._layers[name])

    def _toggle_help(self):
        if self._help_frame.isHidden():
            self._help_frame.show()
            self._help_text.show()
        else:
            self._help_frame.hide()
            self._help_text.hide()

    @staticmethod
    def _process_memory_mb():
        """Return current process working set using only the standard library."""
        try:
            import ctypes
            import ctypes.wintypes

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_=[
                    ("cb",ctypes.wintypes.DWORD),
                    ("PageFaultCount",ctypes.wintypes.DWORD),
                    ("PeakWorkingSetSize",ctypes.c_size_t),
                    ("WorkingSetSize",ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage",ctypes.c_size_t),
                    ("QuotaPagedPoolUsage",ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage",ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage",ctypes.c_size_t),
                    ("PagefileUsage",ctypes.c_size_t),
                    ("PeakPagefileUsage",ctypes.c_size_t),
                ]

            kernel=ctypes.WinDLL("kernel32",use_last_error=True)
            kernel.GetCurrentProcess.restype=ctypes.wintypes.HANDLE
            psapi=ctypes.WinDLL("psapi",use_last_error=True)
            psapi.GetProcessMemoryInfo.argtypes=[
                ctypes.wintypes.HANDLE,ctypes.POINTER(ProcessMemoryCounters),
                ctypes.wintypes.DWORD,
            ]
            psapi.GetProcessMemoryInfo.restype=ctypes.wintypes.BOOL
            counters=ProcessMemoryCounters()
            counters.cb=ctypes.sizeof(counters)
            ok=psapi.GetProcessMemoryInfo(
                kernel.GetCurrentProcess(),ctypes.byref(counters),counters.cb)
            return counters.WorkingSetSize/(1024*1024) if ok else None
        except (AttributeError,OSError):
            return None

    def _set_quality(self,mode):
        if mode not in ("LOW","MEDIUM"):
            return
        self._quality_mode=mode
        for node in self._quality_nodes:
            node.hide() if mode=="LOW" else node.show()
        for label,button in self._quality_buttons.items():
            self._style_control_button(button,active=(label==mode))

    def _draw_network(self, name, routes, color, layer):
        lines=LineSegs(name)
        lines.setThickness(3.2)
        lines.setColor(*color)
        for route in routes:
            if len(route)<2:
                continue
            lines.moveTo(*route[0])
            for point in route[1:]:
                lines.drawTo(*point)
        path=self.render.attachNewNode(lines.create())
        path.setLightOff()
        self.layers[layer].append(path)
        return path

    def _build_network_layers(self, centers):
        electric_routes=[]
        fiber_routes=[]
        mast_boxes=[]
        splitter_boxes=[]
        for zid,(cx,cy) in centers.items():
            # Blue overhead feeder and laterals follow the road grid.
            y=cy-16
            start=(cx-18,cy-18,2.0)
            wire_start=(cx-14,y,7.2)
            wire_end=(cx+14,y,7.2)
            electric_routes.append([start,(cx-14,cy-18,7.2),wire_start,wire_end,(cx+18,cy-18,2.0)])
            for offset in (-10,0,10):
                electric_routes.append([(cx+offset,y,7.2),(cx+offset,y+4,7.2),(cx+offset,y+9,2.2)])
            for offset in (-12,0,12):
                mast_boxes.append(((cx+offset,y,3.6),(.22,.22,7.2)))
            # Red fiber route rides the curb and branches to representative cabinets.
            fiber_y=cy-20.8
            fiber_routes.append([(cx-18,fiber_y,5.45),(cx+18,fiber_y,5.45)])
            for offset in (-18,-6,6,18):
                fiber_routes.append([(cx+offset,fiber_y,5.45),(cx+offset,fiber_y,4.65)])
        self._mesh_batch("electric-distribution-poles",mast_boxes,(.36,.39,.38,1))
        self._mesh_batch("fiber-distribution-cabinets",splitter_boxes,(.42,.43,.40,1))
        self._draw_network("electric-blue-feeders",electric_routes,(.08,.48,1,1),"electrical")
        self._draw_network("telecom-red-fiber",fiber_routes,(1,.12,.19,1),"gpon")

    def _car_prism(self,parent,name,bottom,top,color):
        data=GeomVertexData(name,GeomVertexFormat.getV3(),Geom.UHStatic)
        writer=GeomVertexWriter(data,"vertex")
        triangles=GeomTriangles(Geom.UHStatic)
        first=writer.getWriteRow()
        for point in (*bottom,*top): writer.addData3(*point)
        count=len(bottom)
        for i in range(count):
            nxt=(i+1)%count
            triangles.addVertices(first+i,first+nxt,first+count+nxt)
            triangles.addVertices(first+i,first+count+nxt,first+count+i)
            triangles.addVertices(first,first+i,first+nxt)
            triangles.addVertices(first+count,first+count+nxt,first+count+i)
        geom=Geom(data); geom.addPrimitive(triangles)
        node=GeomNode(name); node.addGeom(geom)
        path=parent.attachNewNode(node); path.setColor(*color); path.setLightOff(); path.setTwoSided(True)
        return path

    def _car_quads(self,parent,name,quads,color):
        data=GeomVertexData(name,GeomVertexFormat.getV3(),Geom.UHStatic)
        writer=GeomVertexWriter(data,"vertex"); triangles=GeomTriangles(Geom.UHStatic)
        for quad in quads:
            first=writer.getWriteRow()
            for point in quad: writer.addData3(*point)
            triangles.addVertices(first,first+1,first+2)
            triangles.addVertices(first,first+2,first+3)
        geom=Geom(data); geom.addPrimitive(triangles)
        node=GeomNode(name); node.addGeom(geom)
        path=parent.attachNewNode(node); path.setColor(*color); path.setLightOff(); path.setTwoSided(True)
        return path

    def _car_boxes(self,parent,name,boxes,color):
        data=GeomVertexData(name,GeomVertexFormat.getV3(),Geom.UHStatic)
        writer=GeomVertexWriter(data,"vertex"); triangles=GeomTriangles(Geom.UHStatic)
        for center,scale in boxes:
            first=writer.getWriteRow()
            for vx,vy,vz in _CUBE_VERTS:
                writer.addData3(center[0]+vx*scale[0],center[1]+vy*scale[1],center[2]+vz*scale[2])
            for a,b,c in _CUBE_TRIS: triangles.addVertices(first+a,first+b,first+c)
        geom=Geom(data); geom.addPrimitive(triangles)
        node=GeomNode(name); node.addGeom(geom)
        path=parent.attachNewNode(node); path.setColor(*color); path.setLightOff()
        return path

    def _car_spheres(self,parent,name,spheres,color,rings=6,sectors=10):
        data=GeomVertexData(name,GeomVertexFormat.getV3(),Geom.UHStatic)
        writer=GeomVertexWriter(data,"vertex"); triangles=GeomTriangles(Geom.UHStatic)
        stride=sectors+1
        for center,scale in spheres:
            first=writer.getWriteRow()
            for ring in range(rings+1):
                latitude=math.pi*ring/rings
                for sector in range(sectors+1):
                    longitude=2*math.pi*sector/sectors
                    writer.addData3(center[0]+scale[0]*math.sin(latitude)*math.cos(longitude),
                                    center[1]+scale[1]*math.sin(latitude)*math.sin(longitude),
                                    center[2]+scale[2]*math.cos(latitude))
            for ring in range(rings):
                for sector in range(sectors):
                    a=first+ring*stride+sector; b=a+stride
                    triangles.addVertices(a,b,a+1); triangles.addVertices(a+1,b,b+1)
        geom=Geom(data); geom.addPrimitive(triangles)
        node=GeomNode(name); node.addGeom(geom)
        path=parent.attachNewNode(node); path.setColor(*color); path.setLightOff(); path.setTwoSided(True)
        return path

    def _build_cars(self,centers):
        paint=[(.62,.14,.10,1),(.70,.72,.69,1),(.10,.27,.42,1),(.66,.49,.22,1)]
        for zone_index,(zid,(cx,cy)) in enumerate(centers.items()):
            # This counter-clockwise loop stays in the right-hand lane; its
            # offset leaves the opposing lane clear and gives each left turn
            # a smooth, low-speed curve through the junction.
            corners=[(cx-20,cy-20),(cx+20,cy-20),(cx+20,cy+20),(cx-20,cy+20)]
            directions=((1,0),(0,1),(-1,0),(0,-1))
            radius=2.2
            route=[]
            for index,corner in enumerate(corners):
                next_corner=corners[(index+1)%4]
                direction=directions[index]
                right=(direction[1],-direction[0])
                outgoing=directions[(index+1)%4]
                next_right=(outgoing[1],-outgoing[0])
                entry_angle=math.atan2(right[1],right[0])
                exit_angle=math.atan2(next_right[1],next_right[0])
                while exit_angle <= entry_angle:
                    exit_angle += 2*math.pi
                start=(corner[0]+right[0]*radius,corner[1]+right[1]*radius)
                end=(next_corner[0]+right[0]*radius,next_corner[1]+right[1]*radius)
                straight=math.dist(start,end)
                arc=radius*(exit_angle-entry_angle)
                route.append({
                    "start":start,"direction":direction,"corner":next_corner,
                    "entry_angle":entry_angle,"radius":radius,
                    "straight":straight,"arc":arc,"length":straight+arc,
                    "axis":"horizontal" if direction[0] else "vertical",
                })
            total=sum(section["length"] for section in route)
            for car_index in range(4):
                root=self.render.attachNewNode(f"CAR-{zid}-{car_index+1}")
                color=paint[(zone_index+car_index)%len(paint)]
                bottom=[(-.56,-1.38,-.12),(.56,-1.38,-.12),(.76,-1.04,-.12),
                        (.82,.92,-.12),(.57,1.38,-.12),(-.57,1.38,-.12),
                        (-.82,.92,-.12),(-.76,-1.04,-.12)]
                top=[(-.52,-1.32,.40),(.52,-1.32,.40),(.70,-.98,.43),
                     (.72,.87,.43),(.52,1.30,.40),(-.52,1.30,.40),
                     (-.70,.87,.43),(-.70,-.98,.43)]
                self._car_prism(root,"car-tapered-body",bottom,top,color)
                cabin_bottom=[(-.62,-.68,.39),(.62,-.68,.39),(.62,.72,.39),(-.62,.72,.39)]
                cabin_top=[(-.43,-.42,.92),(.43,-.42,.92),(.43,.42,.92),(-.43,.42,.92)]
                self._car_prism(root,"car-glass-cabin",cabin_bottom,cabin_top,(.075,.13,.17,1))
                window_color=(.16,.31,.38,1)
                self._car_quads(root,"car-window-glazing",[
                    [(-.37,.665,.48),(.37,.665,.48),(.31,.445,.82),(-.31,.445,.82)],
                    [(.37,-.635,.48),(-.37,-.635,.48),(-.31,-.445,.82),(.31,-.445,.82)],
                    [(.635,-.48,.48),(.635,.48,.48),(.455,.36,.82),(.455,-.36,.82)],
                    [(-.635,.48,.48),(-.635,-.48,.48),(-.455,-.36,.82),(-.455,.36,.82)],
                ],window_color)
                self._car_boxes(root,"car-painted-panels",[
                    ((0,.92,.455),(1.08,.62,.065)),((0,-.99,.445),(1.05,.48,.065)),
                    ((0,0,.955),(.78,.77,.075)),
                    ((-.82,.47,.48),(.16,.18,.12)),((.82,.47,.48),(.16,.18,.12)),
                ],color)
                self._car_boxes(root,"car-bumpers",[
                    ((0,1.37,.02),(1.2,.12,.16)),((0,-1.37,.02),(1.2,.12,.16)),
                ],(.18,.20,.21,1))
                self._car_boxes(root,"car-headlamps",[
                    ((-.46,1.29,.22),(.28,.08,.12)),((.46,1.29,.22),(.28,.08,.12)),
                ],(1,.86,.57,1))
                self._car_boxes(root,"car-tail-lamps",[
                    ((-.47,-1.29,.23),(.25,.08,.15)),((.47,-1.29,.23),(.25,.08,.15)),
                ],(.76,.045,.025,1))
                tires=[]; hubs=[]
                for wx in (-.76,.76):
                    for wy in (-.87,.87):
                        tires.append(((wx,wy,-.02),(.22,.32,.23)))
                        hubs.append(((wx+(.20 if wx>0 else -.20),wy,-.02),(.045,.14,.14)))
                self._car_spheres(root,"car-rubber-tires",tires,(.045,.052,.058,1))
                self._car_spheres(root,"car-metal-wheel-caps",hubs,(.39,.42,.42,1))
                start_distance=(car_index*total/4+zone_index*4.0)%total
                car={
                    "root":root,"route":route,"route_id":zid,"total":total,
                    "distance":start_distance,"start_distance":start_distance,
                    # 5.5–7.3 m/s is below a 30 km/h neighborhood limit.
                    "speed":5.5+car_index*.6,"current_speed":0.0,
                    "braking_for_signal":False,
                }
                self._cars.append(car)
                self._place_car(car)

    def _pedestrian_geometry(self,name,shirt_color):
        """Build one compact, vertex-colored low-poly person mesh."""
        data=GeomVertexData(name,GeomVertexFormat.getV3c4(),Geom.UHStatic)
        vertices=GeomVertexWriter(data,"vertex")
        colors=GeomVertexWriter(data,"color")
        triangles=GeomTriangles(Geom.UHStatic)
        pants=(.20,.23,.27,1)
        skin=(.70,.48,.34,1)
        parts=(
            ((0,0,1.04),(.48,.34,.68),shirt_color),
            ((-.32,0,1.00),(.17,.28,.56),shirt_color),
            ((.32,0,1.00),(.17,.28,.56),shirt_color),
            ((-.13,.07,.37),(.20,.30,.70),pants),
            ((.13,-.07,.37),(.20,.30,.70),pants),
            ((0,0,1.53),(.29,.29,.32),skin),
            ((-.32,0,.66),(.16,.18,.17),skin),
            ((.32,0,.66),(.16,.18,.17),skin),
        )
        for center,size,color in parts:
            for face in _CUBE_FACES:
                first=vertices.getWriteRow()
                for index in face:
                    vx,vy,vz=_CUBE_VERTS[index]
                    vertices.addData3(center[0]+vx*size[0],center[1]+vy*size[1],center[2]+vz*size[2])
                    colors.addData4f(*color)
                triangles.addVertices(first,first+1,first+2)
                triangles.addVertices(first,first+2,first+3)
        geom=Geom(data); geom.addPrimitive(triangles)
        node=GeomNode(name); node.addGeom(geom)
        source=self.render.attachNewNode(node)
        source.setColorOff()
        source.setLightOff()
        return source

    def _build_pedestrians(self,centers):
        """Create a small reusable crowd that walks along the local sidewalks."""
        shirts=((.72,.18,.12,1),(.12,.34,.68,1),(.20,.48,.29,1),
                (.76,.48,.16,1),(.47,.28,.65,1),(.70,.70,.63,1))
        sources={color:self._pedestrian_geometry(f"pedestrian-model-{index+1}",color)
                 for index,color in enumerate(shirts)}
        for zone_index,(zone,(cx,cy)) in enumerate(centers.items()):
            routes=(
                ("vertical",cx-LOCAL_SIDEWALK_OFFSET,cy-10.5,cy+10.5),
                ("vertical",cx+LOCAL_SIDEWALK_OFFSET,cy-10.5,cy+10.5),
                ("horizontal",cy-LOCAL_SIDEWALK_OFFSET,cx-10.5,cx+10.5),
                ("horizontal",cy+LOCAL_SIDEWALK_OFFSET,cx-10.5,cx+10.5),
            )
            for route_index,(axis,fixed,start,end) in enumerate(routes):
                root=self.render.attachNewNode(f"PED-{zone}-{route_index+1}")
                color=shirts[(zone_index+route_index)%len(shirts)]
                sources[color].instanceTo(root)
                record={"root":root,"axis":axis,"fixed":fixed,"start":start,
                        "length":end-start,"phase":route_index*5.0+zone_index*2.0,
                        "speed":.85+(route_index%2)*.2}
                self._pedestrians.append(record)
        for source in sources.values():
            source.detachNode()
        self._update_pedestrians(0.0)

    def _update_pedestrians(self,simulation_time):
        for person in self._pedestrians:
            length=person["length"]
            travel=(person["phase"]+simulation_time*person["speed"])%(2*length)
            direction=1 if travel<=length else -1
            offset=travel if direction>0 else 2*length-travel
            along=person["start"]+offset
            if person["axis"]=="vertical":
                x,y=person["fixed"],along
                dx,dy=0,direction
            else:
                x,y=along,person["fixed"]
                dx,dy=direction,0
            person["root"].setPos(x,y,.025+abs(math.sin(simulation_time*7+person["phase"]%math.tau))*.035)
            person["root"].setH(math.degrees(math.atan2(-dx,dy)))

    def _place_car(self,car):
        distance=car["distance"]%car["total"]
        section_start=0.0
        for section in car["route"]:
            local=distance-section_start
            if local < section["length"]:
                if local < section["straight"]:
                    x=section["start"][0]+section["direction"][0]*local
                    y=section["start"][1]+section["direction"][1]*local
                    dx,dy=section["direction"]
                else:
                    angle=section["entry_angle"]+(local-section["straight"])/section["radius"]
                    x=section["corner"][0]+section["radius"]*math.cos(angle)
                    y=section["corner"][1]+section["radius"]*math.sin(angle)
                    dx,dy=-math.sin(angle),math.cos(angle)
                car["root"].setPos(x,y,.55)
                # Panda3D's positive heading turns local +Y toward world -X.
                # Negating dx keeps the car's nose aligned with its path tangent.
                car["root"].setH(math.degrees(math.atan2(-dx,dy)))
                return
            section_start += section["length"]

    def _advance_car(self,car,simulation_time,dt):
        distance=car["distance"]
        section_start=0.0
        speed=car["current_speed"]
        braking=5.0
        acceleration=2.2
        advance=speed*dt
        for section in car["route"]:
            local=distance-section_start
            if 0 <= local < section["straight"]:
                intersection=(int(section["corner"][0]),int(section["corner"][1]))
                signal_heads=self._intersection_signals[intersection][section["axis"]]
                state=signal_heads[0]["state"]
                # The car's nose must stop behind the painted line, not on it.
                stop_line=section["straight"]-6.5
                distance_to_stop=stop_line-local
                if distance_to_stop >= 0 and state != "green":
                    stopping_distance=(speed*speed)/(2*braking)
                    if car["braking_for_signal"] or distance_to_stop <= stopping_distance + speed*dt:
                        car["braking_for_signal"]=True
                        speed=max(0.0,speed-braking*dt)
                        advance=min(speed*dt,distance_to_stop)
                    else:
                        speed=min(car["speed"],speed+acceleration*dt)
                        advance=speed*dt
                else:
                    car["braking_for_signal"]=False
                    speed=min(car["speed"],speed+acceleration*dt)
                    advance=speed*dt
                break
            if local < section["length"]:
                # Once a car has entered the junction, it clears the crossing
                # even if the signal changes while it is turning.
                speed=min(car["speed"],speed+acceleration*dt)
                advance=speed*dt
                break
            section_start += section["length"]
        car["current_speed"]=speed
        return distance+advance

    def _update_city(self,simulation_time,dt=0.0):
        active_index={"red":0,"yellow":1,"green":2}
        phase=simulation_time%20.0
        glow=1.0+.12*math.sin(phase*math.tau/1.25)
        self._lighting_elapsed += max(0.0,dt)
        if self._lighting_elapsed >= .15:
            self._update_lighting(simulation_time)
            self._lighting_elapsed = 0.0
        for signal in self._traffic_signals:
            signal["state"]=self._signal_state(signal["axis"],simulation_time)
            active=active_index[signal["state"]]
            for index,lens in enumerate(signal["lenses"]):
                if index==active:
                    lens.setColorScale(glow,glow,glow,1)
                    signal["halos"][index].show()
                    signal["halos"][index].setColorScale(1,1,1,.85+.15*glow)
                else:
                    lens.setColorScale(.13,.13,.13,1)
                    signal["halos"][index].hide()
        if dt > 0 and self._cars:
            for route_id in {car["route_id"] for car in self._cars}:
                ordered=sorted((car for car in self._cars if car["route_id"]==route_id),
                               key=lambda car:car["distance"])
                proposed=[self._advance_car(car,simulation_time,dt) for car in ordered]
                desired=proposed.copy()
                # Keep a safe following gap so red lights cannot make cars
                # overlap or pass one another on the same district route.
                for index in range(len(ordered)-1,-1,-1):
                    leader=proposed[index+1] if index+1<len(ordered) else proposed[0]+ordered[index]["total"]
                    proposed[index]=min(proposed[index],leader-4.5)
                    if proposed[index] < desired[index]:
                        progress=max(0.0,proposed[index]-ordered[index]["distance"])
                        ordered[index]["current_speed"]=min(
                            ordered[index]["current_speed"],progress/max(dt,1e-6))
                for car,distance in zip(ordered,proposed):
                    car["distance"]=distance%car["total"]
        for car in self._cars:
            self._place_car(car)
        self._update_pedestrians(simulation_time)

    def _update_lighting(self, simulation_time):
        """Blend the automatic cycle or apply a user-selected lighting preset."""
        cycle=(simulation_time%180.0)/180.0
        if self._time_of_day_override:
            presets={
                "DAY":((.48,.52,.57),(.82,.78,.69),(.035,.055,.075),"D\u00cdA",.30,-34),
                "AFTERNOON":((.43,.45,.48),(.95,.67,.43),(.13,.12,.12),"TARDE",.58,-22),
                "NIGHT":((.23,.27,.36),(.22,.26,.37),(.018,.03,.06),"NOCHE",1.35,0),
            }
            ambient,sun,sky,phase_name,window_brightness,sun_pitch=presets[self._time_of_day_override]
        else:
            stops=(
                (0.0,(.48,.52,.57),(.82,.78,.69),(.035,.055,.075),"D\u00cdA",.30),
                (.28,(.43,.45,.48),(.95,.67,.43),(.13,.12,.12),"TARDE",.55),
                (.43,(.22,.25,.34),(.50,.31,.27),(.045,.055,.09),"ATARDECER",1.0),
                (.55,(.23,.27,.36),(.22,.26,.37),(.018,.03,.06),"NOCHE",1.35),
                (.82,(.23,.27,.36),(.22,.26,.37),(.018,.03,.06),"NOCHE",1.35),
                (.94,(.40,.43,.48),(.89,.62,.42),(.10,.10,.13),"AMANECER",.72),
                (1.0,(.48,.52,.57),(.82,.78,.69),(.035,.055,.075),"D\u00cdA",.30),
            )
            for left,right in zip(stops,stops[1:]):
                if left[0]<=cycle<=right[0]:
                    blend=(cycle-left[0])/max(right[0]-left[0],1e-6)
                    def lerp(a,b):
                        return tuple(x+(y-x)*blend for x,y in zip(a,b))
                    ambient=lerp(left[1],right[1])
                    sun=lerp(left[2],right[2])
                    sky=lerp(left[3],right[3])
                    phase_name=left[4] if blend<.55 else right[4]
                    window_brightness=left[5]+(right[5]-left[5])*blend
                    break
            sun_pitch=-8.0-48.0*max(0.0,math.sin((cycle-.12)*math.tau))
        self._ambient_light.setColor(Vec4(*ambient,1))
        self._sun_light.setColor(Vec4(*sun,1))
        self._sun_node.setHpr(-38,sun_pitch,0)
        self.setBackgroundColor(*sky,1)
        for windows in self._lit_window_nodes:
            windows.setColorScale(window_brightness,window_brightness,window_brightness,1)
        for bulb in self._lamp_bulbs:
            bulb.setColorScale(window_brightness,window_brightness*.91,window_brightness*.65,1)
        self._hud_time.setText(f"CICLO: {phase_name}")

    def _animate_city(self,task):
        # AsyncTask.dt can be nearly zero when Panda3D runs several frames
        # between clock updates. Read the clock directly so traffic advances
        # with elapsed simulation time instead of depending on render cadence.
        frame_dt=max(0.0,float(ClockObject.getGlobalClock().getDt()))
        simulation_dt=0.0 if self._paused else min(frame_dt,.1)
        self._simulation_time += simulation_dt
        self._update_city(self._simulation_time,simulation_dt)
        self._perf_frames += 1
        self._perf_elapsed += frame_dt
        self._perf_refresh_elapsed += frame_dt
        if self._perf_refresh_elapsed >= 1.0:
            fps=self._perf_frames/max(self._perf_elapsed,1e-6)
            memory=self._process_memory_mb()
            ram=f"{memory:.0f}" if memory is not None else "N/D"
            self._hud_perf.setText(f"FPS {fps:.0f}  |  MEMORIA {ram} MB")
            self._perf_frames=0
            self._perf_elapsed=0.0
            self._perf_refresh_elapsed=0.0
        return task.cont

    def _toggle_pause(self):
        self._paused=not self._paused
        self._pause_button["text"]="REANUDAR" if self._paused else "PAUSAR"
        self._style_control_button(self._pause_button,active=self._paused)

    def _reset_simulation(self):
        self._paused=False
        self._simulation_time=0.0
        self._time_of_day_override=None
        self._lighting_elapsed=0.0
        self._pause_button["text"]="PAUSAR"
        self._style_control_button(self._pause_button)
        for mode,button in self._time_buttons.items():
            self._style_control_button(button,active=(mode=="AUTO"))
        for car in self._cars:
            car["distance"]=car["start_distance"]
            car["current_speed"]=0.0
            car["braking_for_signal"]=False
        self._update_city(0.0,0.0)
        self._update_lighting(0.0)

    def _set_time_of_day(self,mode):
        if mode not in ("AUTO","DAY","AFTERNOON","NIGHT"):
            return
        self._time_of_day_override=None if mode=="AUTO" else mode
        for label,button in self._time_buttons.items():
            self._style_control_button(button,active=(label==mode))
        self._update_lighting(self._simulation_time)

    def _toggle_layer(self, name):
        self._layers[name] = not self._layers[name]
        for node in self.layers[name]:
            node.show() if self._layers[name] else node.hide()
        button=self._layer_buttons.get(name)
        if button:
            self._style_control_button(button,active=self._layers[name])

    def _focus_zone(self, zone):
        if zone not in getattr(self,"_zone_centers",{}):
            return
        self._active_zone=zone
        for label,button in self._zone_buttons.items():
            self._style_control_button(button,active=(label==zone))
        x,y=self._zone_centers[zone]
        self._camera_pivot.setPos(x,y,0)
        self._camera_distance=78.0
        self._place_camera_at_distance()
        self.camera.lookAt(0,0,1)

    def _zoom(self, factor):
        self._camera_distance = max(18.0, min(235.0, self._camera_distance * factor))
        self._place_camera_at_distance()
        self.camera.lookAt(0, 0, 1)

    def _key_down(self, key):
        self._keys_down.add(key)

    def _key_up(self, key):
        self._keys_down.discard(key)

    def _keyboard_navigate(self, dt):
        keys = self._keys_down
        if not keys:
            return
        step = 34.0 * min(dt, .1)
        forward = int("w" in keys or "arrow_up" in keys) - int("s" in keys or "arrow_down" in keys)
        sideways = int("d" in keys or "arrow_right" in keys) - int("a" in keys or "arrow_left" in keys)
        # Move relative to the current camera heading; normalize diagonals so
        # pressing two keys does not make travel faster.
        length = math.hypot(forward, sideways)
        if length:
            forward /= length
            sideways /= length
            heading = math.radians(self._camera_pivot.getH())
            dx = (math.cos(heading) * sideways + math.sin(heading) * forward) * step
            dy = (-math.sin(heading) * sideways + math.cos(heading) * forward) * step
            self._camera_pivot.setX(max(-82.0, min(82.0, self._camera_pivot.getX() + dx)))
            self._camera_pivot.setY(max(-82.0, min(82.0, self._camera_pivot.getY() + dy)))
        turn = 65.0 * min(dt, .1)
        if "q" in keys:
            self._camera_pivot.setH(self._camera_pivot.getH()+turn)
        if "e" in keys:
            self._camera_pivot.setH(self._camera_pivot.getH()-turn)
        if "+" in keys or "=" in keys:
            self._zoom(.985 ** (dt*60))
        if "-" in keys or "_" in keys:
            self._zoom(1.015 ** (dt*60))

    def _mouse_update(self, task):
        self._keyboard_navigate(task.dt)
        if self.mouseWatcherNode is None:
            self._previous_mouse=None
        elif self.mouseWatcherNode.hasMouse():
            mouse = self.mouseWatcherNode.getMouse()
            current = (mouse.getX(),mouse.getY())
            if self._previous_mouse is not None:
                dx=current[0]-self._previous_mouse[0]; dy=current[1]-self._previous_mouse[1]
                if self.mouseWatcherNode.isButtonDown("mouse3"):
                    self._camera_pivot.setH(self._camera_pivot.getH()-dx*110)
                    self._camera_pivot.setP(max(-18,min(45,self._camera_pivot.getP()+dy*90)))
                elif self.mouseWatcherNode.isButtonDown("mouse2"):
                    self._camera_pivot.setX(self._camera_pivot.getX()-dx*70)
                    self._camera_pivot.setY(self._camera_pivot.getY()+dy*70)
            self._previous_mouse=current
        else:
            self._previous_mouse=None
        return task.cont

    def _select_asset(self):
        if not self.mouseWatcherNode.hasMouse():
            return
        mouse=self.mouseWatcherNode.getMouse()
        self._pick_asset_at(mouse.getX(),mouse.getY())

    def _pick_asset_at(self, x, y):
        self._mouse_ray.setFromLens(self.camNode,x,y)
        self._pick_queue.clearEntries()
        self._picker.traverse(self.render)
        if not self._pick_queue.getNumEntries():
            return None
        self._pick_queue.sortEntries()
        path=self._pick_queue.getEntry(0).getIntoNodePath().findNetPythonTag("asset_id")
        if path.isEmpty():
            return None
        asset_id=path.getPythonTag("asset_id")
        if self._selected_node and not self._selected_node.isEmpty():
            self._selected_node.clearColorScale()
        self._selected=asset_id
        self._selected_node=path
        self._selected_node.setColorScale(1.35,1.25,.72,1)
        self._hud_selection.setText(f"Activo seleccionado: {asset_id}")
        if self._selection_queue is not None:
            try:
                self._selection_queue.put_nowait({"asset_id": asset_id})
            except Exception:
                pass
        return asset_id


def run_city():
    app=SmartCityApp()
    app.run()
