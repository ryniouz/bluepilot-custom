"""Every bluepilot/ui/console/form.py row on one page, for the component sheet (scene form_gallery)."""

from bluepilot.ui.console.form import Action, Choice, FormPage, Info, Meter, Nav, Note, Section, Stepper, Toggle
from bluepilot.ui.lib.theme import Console


class FormGallery(FormPage):
  def __init__(self):
    super().__init__()
    self.on = True
    self.seg = 1
    self.radio = 0
    self.n = 3

  def sections(self):
    return [
      Section("Toggles and choices", "sliders", [
        Toggle("Lane keeping", "Keeps the truck centred", self.on, lambda: setattr(self, "on", not self.on)),
        Toggle("Disabled toggle", "Greyed out, can't be changed while driving", False, None, enabled=False),
        Choice("Driving personality", ["Relaxed", "Standard", "Aggressive"], self.seg, lambda i: setattr(self, "seg", i)),
        Stepper("Follow distance", f"{self.n} s", lambda: None, lambda: None, sub="Gap to the car ahead"),
      ], note="A section note: one or two muted lines under the rows."),
      Section("Radio list", "cpu", [
        Choice("Driving model", ["Default model", "Experimental model", "Previous model"], self.radio,
               lambda i: setattr(self, "radio", i), subs=["Recommended", "Smoother in traffic", "Last release"]),
      ]),
      Section("Information", "list", [
        Info("Branch", "console-ui"),
        Info("Status", "Up to date", dot=Console.SUCCESS),
        Meter("Storage used", "41 %", 0.41),
        Meter("12 V charge", "86 %", 0.86, Console.SUCCESS, target=0.5),
      ]),
      Section("Navigation and actions", "chevron", [
        Nav("Wi-Fi", "Home network", lambda: None, value="Connected"),
        Action("Check for updates", "Last checked 5 min ago", "Check", lambda: None, primary=True),
        Action("Reset calibration", "Recalibrates on the next drive", "Reset", lambda: None, danger=True),
        Note("Notes can also sit between rows, without a divider."),
      ]),
    ]
