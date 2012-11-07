#!/usr/bin/python3

from gi.repository import Gtk

from ubiquity.plugin_manager import load_plugin
import sys

# we could use this as the base for the MockController as well
#   from ubiquity.frontend.base import Controller

# to test for real:
#   - qemu create -f qcow2 random-image 80G
#   - get a VM and boot with 
#     kvm -snapshot -hda random-image -cdrom quantal-desktop.iso -boot d -m 1600
# Run:
"""
sudo apt-get install bzr 
bzr co --lightweight lp:~mvo/ubiquity/ssologin
cd ssologin
sudo cp ubiquity/plugins/* /usr/lib/ubiquity/plugins && sudo cp gui/gtk/*.ui /usr/share/ubiquity/gtk && sudo ./bin/ubiquity
"""

class MockController(object):

    def __init__(self):
        self.oem_user_config = None
        self.oem_config = None
        self.dbfilter = None
        self._allow_go_foward = True
        self._allow_go_backward = True

    def add_builder(self, builder):
        pass

    def allow_go_forward(self, v):
        self._allow_go_forward = v

    def allow_go_backward(self, v):
        self._allow_go_backward = v


if __name__ == "__main__":
    """
    UBIQUITY_PLUGIN_PATH=./ubiquity/plugins/ \
    UBIQUITY_GLADE=./gui/gtk \
    ./plugin-viewer-gtk.py ubi-ubuntuone
    """
    plugin_name = sys.argv[1]
    plugin_module = load_plugin(plugin_name)
    mock_controller = MockController()
    page_gtk = plugin_module.PageGtk(mock_controller)

    button_next = Gtk.Button("next")
    button_next.connect(
        "clicked", lambda b: page_gtk.plugin_on_next_clicked())
    button_prev = Gtk.Button("prev")
    button_prev.connect(
        "clicked", lambda b: page_gtk.plugin_on_back_clicked())

    button_box = Gtk.ButtonBox(spacing=12)
    button_box.set_layout(Gtk.ButtonBoxStyle.END)
    button_box.pack_start(button_prev, True, True, 6)
    button_box.pack_start(button_next, True, True, 6)

    box = Gtk.VBox()
    box.pack_start(page_gtk.page, True, True, 6)
    box.pack_start(button_box, True, True, 6)

    win = Gtk.Window()
    win.add(box)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()

    Gtk.main()
