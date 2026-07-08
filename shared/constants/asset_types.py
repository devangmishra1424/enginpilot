from enum import Enum

class AssetClass(str, Enum):
    UPS = "UPS"
    BATTERY = "Battery"
    TRANSFORMER = "Transformer"
    SWITCHGEAR = "Switchgear"
    PDU = "PDU"
    CHILLER = "Chiller"
    CRAH = "CRAH"
    PUMP = "Pump"
    RACK = "Rack"