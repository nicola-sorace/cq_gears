#! /usr/bin/python3

'''
CQ_Gears - CadQuery based involute profile gear generator

Copyright 2021 meadiode@github

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
'''

from __future__ import annotations
import numpy as np
import cadquery as cq
from inspect import signature


class GearBase:
    ka = 1.0  # Addendum coefficient
    kd = 1.25 # Dedendum coefficient

    curve_points = 20 # Number of points to approximate a curve
    surface_splines = 5 # Number of curve splines to approximate a surface
    
    wire_comb_tol = 1e-2 # Wire combining tolerance
    spline_approx_tol = 1e-2 # Surface spline approximation tolerance
    shell_sewing_tol = 1e-2 # Tolerance to assembly a shell out of faces
    isection_tol = 1e-7 # Tolerance to find intersections between two surfaces
    spline_approx_min_deg = 3 # Minimum surface spline degree
    spline_approx_max_deg = 8 # Maximum surface spline degree

    working_plane = 'XY'
    axial_plane = 'XZ'
    rotation_axis = 'Z'

    tooth_trace_curve_segments = (1.0,)

    def __init__(self, *args, **kv_args):
        raise NotImplementedError('Constructor is not defined')

    
    def build(self, **kv_params):
        params = {**self.build_params, **kv_params}
        
        return self._build(**params)


class PostProcMixin:

    postproc_sequence = (
        'bore',
        'recess',
        'hub',
        'spokes',
        'chamfer',
    )

    def _post_process(self, body: cq.Solid, **params) -> cq.Solid:
        
        for pp_name in self.postproc_sequence:
            pp = getattr(self, pp_name)
            sig = signature(pp)

            args = {k: v.default if v.default is not sig.empty else None \
                        for k, v in sig.parameters.items() if k != 'body'}

            for k in params:
                if k in args:
                    args[k] = params[k]

            body = pp(body, **args)

        return body


    def bore(self, body: cq.Solid, bore_d: float | None) -> cq.Solid:
        if bore_d is None:
            return body

        body = (cq.Workplane(self.working_plane)
                .add(body)
                .faces('<' + self.rotation_axis)
                .workplane()
                .circle(bore_d / 2.0)
                .cutThruAll()
               ).val()

        return body


    def recess(self, body: cq.Solid, recess: float | None,
               recess_d: float, hub_d: float | None) -> cq.Solid:
        
        if recess is None:
            return body

        body = (cq.Workplane(self.working_plane)
                .add(body)
                .faces('>' + self.rotation_axis)
                .workplane())

        if hub_d is not None:
            body = body.circle(hub_d / 2.0)

        body = body.circle(recess_d / 2.0).cutBlind(-recess).val()

        return body


    def hub(self, body: cq.Solid, hub_length: float | None,
            hub_d: float, bore_d: float | None) -> cq.Solid:
        
        if hub_length is None:
            return body

        assert hub_d is not None, 'Hub diameter is not set'

        body = (cq.Workplane(self.working_plane)
                .add(body)
                .faces('>' + self.rotation_axis)
                .workplane())

        if bore_d is not None:
            body = body.circle(bore_d / 2.0)

        body = body.circle(hub_d / 2.0).extrude(hub_length)

        return body.val()


    def spokes(self, body: cq.Solid, n_spokes: int | None,
               spokes_id: float | None, spokes_od: float | None,
               spoke_width: float, spoke_fillet: float) -> cq.Solid:
        if n_spokes is None:
            return body
        assert n_spokes > 1, 'Number of spokes must be > 1'
        assert spoke_width is not None, 'Spoke width is not set'
        assert spokes_od is not None, 'Outer spokes diameter is not set'

        if spokes_id is None:
            r1 = spoke_width / 2.0
        else:
            r1 = max(spoke_width / 2.0, spokes_id / 2.0)

        r2 = spokes_od / 2.0

        r1 += 0.0001
        r2 -= 0.0001

        tau = np.pi * 2.0 / n_spokes
        a1 = np.arcsin((spoke_width / 2.0) / (spokes_id / 2.0))
        a2 = np.arcsin((spoke_width / 2.0) / (spokes_od / 2.0))
        a3 = tau - a2
        a4 = tau - a1

        cutout = (cq.Workplane(self.working_plane).workplane(offset=-0.1)
                  .moveTo(np.cos(a1) * r1, np.sin(a1) * r1)
                  .lineTo(np.cos(a2) * r2, np.sin(a2) * r2)
                  .radiusArc((np.cos(a3) * r2, np.sin(a3) * r2), -r2)
                  .lineTo(np.cos(a4) * r1, np.sin(a4) * r1)
                  .radiusArc((np.cos(a1) * r1, np.sin(a1) * r1), r1)
                  .close()
                  .extrude(self.width + 1.0))

        if spoke_fillet is not None:
            cutout = cutout.edges('|' + self.rotation_axis).fillet(spoke_fillet)

        body = cq.Workplane(self.working_plane).add(body)

        for i in range(n_spokes):
            body = body.cut(cutout.rotate((0.0, 0.0, 0.0),
                                          (0.0, 0.0, 1.0),
                                          np.degrees(tau * i)))

        return body.val()


    def chamfer(self, body: cq.Solid,
                chamfer: float | tuple[float, float] | None,
                chamfer_top: float | tuple[float, float] | None,
                chamfer_bottom: float | tuple[float, float] | None) -> cq.Solid:
        E = 0.01
        
        if chamfer is None and chamfer_top is None and chamfer_bottom is None:
            return body
        
        if chamfer is not None:
            if chamfer_top is None:
                chamfer_top = chamfer
            if chamfer_bottom is None:
                chamfer_bottom = chamfer
                
        if chamfer_top is not None:
            if isinstance(chamfer_top, (list, tuple)):
                wx, wy = chamfer_top
            else:
                wx, wy = chamfer_top, chamfer_top
                
            cutter = (cq.Workplane(self.axial_plane)
                      .moveTo(self.ra - wx, self.width + E)
                      .hLine(wx + E)
                      .vLine(-wy - E)
                      .close()
                      .revolve())

            body = (cq.Workplane(self.working_plane)
                    .add(body)
                    .cut(cutter))
            
        if chamfer_bottom is not None:
            if isinstance(chamfer_bottom, (list, tuple)):
                wx, wy = chamfer_bottom
            else:
                wx, wy = chamfer_bottom, chamfer_bottom
                
            cutter = (cq.Workplane(self.axial_plane)
                      .moveTo(self.ra + E, wy)
                      .vLine(-wy - E)
                      .hLine(-wx - E)
                      .close()
                      .revolve())

            body = (cq.Workplane(self.working_plane)
                    .add(body)
                    .cut(cutter))
            
            
        return body.val()