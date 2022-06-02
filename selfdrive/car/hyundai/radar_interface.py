#!/usr/bin/env python3
import math

from cereal import car
from opendbc.can.parser import CANParser
from selfdrive.car.interfaces import RadarInterfaceBase
from selfdrive.car.hyundai.values import DBC

RADAR_START_ADDR = 0x500
RADAR_MSG_COUNT = 32


def get_radar_can_parser(CP):
  if CP.enhancedScc:

    signals = []
    checks = []

    signals += [
      ("ObjValid", "ESCC_SCC11"),
      ("ACC_ObjLatPos", "ESCC_SCC11"),
      ("ACC_ObjDist", "ESCC_SCC11"),
      ("ACC_ObjRelSpd", "ESCC_SCC11"),
    ]
    checks += [
      ("ESCC_SCC11", 50),
    ]
    return CANParser(DBC[CP.carFingerprint]['pt'], signals, checks, 0)
  else:
    if DBC[CP.carFingerprint]['radar'] is None:
      return None

    signals = []
    checks = []

    for addr in range(RADAR_START_ADDR, RADAR_START_ADDR + RADAR_MSG_COUNT):
      msg = f"RADAR_TRACK_{addr:x}"
      signals += [
        ("STATE", msg),
        ("AZIMUTH", msg),
        ("LONG_DIST", msg),
        ("REL_ACCEL", msg),
        ("REL_SPEED", msg),
      ]
      checks += [(msg, 50)]
    return CANParser(DBC[CP.carFingerprint]['radar'], signals, checks, 1)


class RadarInterface(RadarInterfaceBase):
  def __init__(self, CP):
    super().__init__(CP)
    self.updated_messages = set()
    self.trigger_msg = 0x2CA if CP.enhancedScc else RADAR_START_ADDR + RADAR_MSG_COUNT - 1
    self.track_id = 0

    self.radar_off_can = not CP.enhancedScc or CP.radarOffCan
    self.rcp = get_radar_can_parser(CP)
    self.enhanced_scc = CP.enhancedScc

  def update(self, can_strings):
    if self.radar_off_can or (self.rcp is None):
      return super().update(None)

    vls = self.rcp.update_strings(can_strings)
    self.updated_messages.update(vls)

    if self.trigger_msg not in self.updated_messages:
      return None

    rr = self._update(self.updated_messages)
    self.updated_messages.clear()

    return rr

  def _update(self, updated_messages):
    ret = car.RadarData.new_message()
    if self.rcp is None:
      return ret

    errors = []

    if not self.rcp.can_valid:
      errors.append("canError")
    ret.errors = errors

    if self.enhanced_scc:
      msg = self.rcp.vl
      valid = msg["ESCC_SCC11"]['ObjValid']
      if valid:
        for ii in range(1):
          if ii not in self.pts:
            self.pts[ii] = car.RadarData.RadarPoint.new_message()
            self.pts[ii].trackId = self.track_id
            self.track_id += 1
          self.pts[ii].measured = True
          self.pts[ii].dRel = msg["ESCC_SCC11"]['ACC_ObjDist']
          self.pts[ii].yRel = -msg["ESCC_SCC11"]['ACC_ObjLatPos']
          self.pts[ii].vRel = msg["ESCC_SCC11"]['ACC_ObjRelSpd']
          self.pts[ii].aRel = float('nan')
          self.pts[ii].yvRel = float('nan')
    else:
      for addr in range(RADAR_START_ADDR, RADAR_START_ADDR + RADAR_MSG_COUNT):
        msg = self.rcp.vl[f"RADAR_TRACK_{addr:x}"]

        if addr not in self.pts:
          self.pts[addr] = car.RadarData.RadarPoint.new_message()
          self.pts[addr].trackId = self.track_id
          self.track_id += 1

        valid = msg['STATE'] in (3, 4)
        if valid:
          azimuth = math.radians(msg['AZIMUTH'])
          self.pts[addr].measured = True
          self.pts[addr].dRel = math.cos(azimuth) * msg['LONG_DIST']
          self.pts[addr].yRel = 0.5 * -math.sin(azimuth) * msg['LONG_DIST']
          self.pts[addr].vRel = msg['REL_SPEED']
          self.pts[addr].aRel = msg['REL_ACCEL']
          self.pts[addr].yvRel = float('nan')

        else:
          del self.pts[addr]

    ret.points = list(self.pts.values())
    return ret
