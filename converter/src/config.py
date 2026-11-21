"""Paths and fixed limits shared by the converter modules."""
import os

CONVERTER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(CONVERTER_DIR)
PROFILE_DIR = os.path.join(CONVERTER_DIR, "profiles")
TEMPLATE_DIR = os.path.join(CONVERTER_DIR, "template")
OUTPUT_DIR = os.path.join(ROOT, "3mf")

MATERIALS = {"pla": "#F2754E", "petg": "#3E8ED0"}  # material -> preview colour
HOTEND_MAX_C, BED_MAX_C = 260, 100   # Ender-3 V3 SE hardware limits
MAX_PLATES = 36      # MAX_PLATE_COUNT in the slicer source (PartPlate.hpp)
PLATE_GAP = 0.2      # LOGICAL_PART_PLATE_GAP: plates sit 1.2 bed widths apart
GENERIC_DIRS = {"files", "stl", "stls", "models"}   # folder names too vague to name an output after
THUMB, THUMB_SMALL = 300, 96
