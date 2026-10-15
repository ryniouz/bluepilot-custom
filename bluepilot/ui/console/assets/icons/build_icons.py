"""Build the Console's pack icons: copy each chosen SVG into src/ and rasterise white alpha masks at 48, 96 and 192 px.

Off-device only (needs cairosvg). Packs come from their npm tarballs:
  @phosphor-icons/core (MIT), @tabler/icons (MIT), @fluentui/svg-icons (MIT)
  python build_icons.py <dir with the unpacked tarballs>   # or with no argument to re-rasterise src/ only

Lucas's picks (2026-10-15): alerts, notifications and general warnings from Phosphor; front-facing vehicles from Phosphor;
collision from Fluent UI; road, connectivity and navigation from Tabler; the steering wheel is a drawn Ford F-150 wheel;
any icon for his own vehicle is a pickup. One stroke weight everywhere: 1.5 on the 24-unit grid (Phosphor Regular's
weight, Tabler set to match).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
SIZES = (48, 96, 192)
STROKE = "1.5"

# Console icon name -> (pack, file in that pack). "custom" files are drawn here, already in src/.
ICONS = {
  # Phosphor Regular: alerts, notifications, general warnings, front-facing vehicles
  "warning": ("phosphor", "warning"),
  "alert": ("phosphor", "warning-circle"),
  "bell": ("phosphor", "bell"),
  "eye": ("phosphor", "eye"),
  "timer": ("phosphor", "timer"),
  "rec": ("phosphor", "record"),
  "light": ("phosphor", "traffic-signal"),
  "car_front": ("phosphor", "car"),
  "info_circle": ("phosphor", "info"),
  # Fluent UI Regular: collision
  "collision": ("fluent", "vehicle_car_collision_24_regular"),
  # Tabler (stroke 1.5): road, connectivity, navigation, rail picks
  "road": ("tabler", "road"),
  "cell": ("tabler", "antenna-bars-5"),
  "bluetooth": ("tabler", "bluetooth"),
  "cloud": ("tabler", "cloud"),
  "map": ("tabler", "map"),
  "lane_left": ("tabler", "arrow-ramp-left"),
  "lane_right": ("tabler", "arrow-ramp-right"),
  "signal_left": ("tabler", "arrow-big-left"),
  "signal_right": ("tabler", "arrow-big-right"),
  "signal_left_on": ("tabler-filled", "arrow-big-left"),
  "signal_right_on": ("tabler-filled", "arrow-big-right"),
  "energy": ("tabler", "battery-charging"),
  "charging": ("tabler", "charging-pile"),
  # Drawn for Citadel
  "wheel": ("custom", "ford-wheel"),
  "car": ("custom", "pickup"),
  "hands": ("custom", "hands-wheel"),
}

PACK_DIRS = {
  "phosphor": "_phosphor-icons_core/package/assets/regular/{}.svg",
  "fluent": "_fluentui_svg-icons/package/icons/{}.svg",
  "tabler": "_tabler_icons/package/icons/outline/{}.svg",
  "tabler-filled": "_tabler_icons/package/icons/filled/{}.svg",
}


def fetch(dl: str):
  for name, (pack, f) in ICONS.items():
    if pack == "custom":
      continue
    svg = open(os.path.join(dl, PACK_DIRS[pack].format(f))).read()
    if pack == "tabler":
      svg = svg.replace('stroke-width="2"', f'stroke-width="{STROKE}"')
    open(os.path.join(SRC, f"{name}.svg"), "w").write(f"<!-- {pack}: {f} -->\n" + svg)


def rasterise():
  import cairosvg
  for size in SIZES:
    os.makedirs(os.path.join(HERE, str(size)), exist_ok=True)
  for name, (pack, f) in ICONS.items():
    path = os.path.join(SRC, f"{(f if pack == 'custom' else name)}.svg")
    svg = open(path).read().replace("currentColor", "#ffffff")
    if pack in ("fluent",) and 'fill=' not in svg.split(">", 2)[1]:
      svg = svg.replace("<svg ", '<svg fill="#ffffff" ', 1)
    for size in SIZES:
      cairosvg.svg2png(bytestring=svg.encode(), write_to=os.path.join(HERE, str(size), f"{name}.png"), output_width=size, output_height=size)


if __name__ == "__main__":
  if len(sys.argv) > 1:
    fetch(sys.argv[1])
  rasterise()
