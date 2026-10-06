"""Home page: a short welcome and an at-a-glance overview of key settings.

The cards do not repeat the sidebar: each one shows the real state of one
area of the computer and opens the exact setting when clicked.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
import os  # noqa: E402

from gi.repository import Gio, GLib, Gtk  # noqa: E402

from base_page import STATUS_ERROR, BaseSettingsPage, _  # noqa: E402
from config import ICONS_DIR  # noqa: E402

logger = logging.getLogger("biglinux-settings")

# Card states
ON, OFF, WARNING, HIDDEN = "on", "off", "warning", "hidden"


@dataclass(frozen=True)
class CardSpec:
    """One overview card.

    scripts: check scripts queried in parallel; describe() turns their
    results ({script: True/False/None}) into (state, text).
    """

    card_id: str
    title: str
    icon: str
    color: str
    page_id: str
    target_script: str
    scripts: tuple[str, ...]
    describe: Callable[[dict], tuple[str, str]]


def _ssh(states: dict) -> tuple[str, str]:
    running = states.get("system/sshStart.sh")
    if running is None:
        return HIDDEN, ""
    if running:
        return ON, _("On")
    return OFF, _("Off")


def _profile(states: dict) -> tuple[str, str]:
    performance = states.get("performance/cpuMaximumPerformance.sh")
    if performance is None:
        return HIDDEN, ""
    if performance:
        return ON, _("Performance")
    return OFF, _("Standard")


_OLLAMA = (
    "ai/ollamaCpu.sh",
    "ai/ollamaVulkan.sh",
    "ai/ollamaNvidia.sh",
    "ai/ollamaAmd.sh",
)


def _local_ai(states: dict) -> tuple[str, str]:
    if all(states.get(s) is None for s in _OLLAMA):
        return HIDDEN, ""
    if any(states.get(s) for s in _OLLAMA):
        return ON, _("Ollama installed")
    return OFF, _("Not set up")


def _docker(states: dict) -> tuple[str, str]:
    enabled = states.get("docker/dockerEnable.sh")
    if enabled is None:
        return HIDDEN, ""
    if enabled:
        return ON, _("Running")
    return OFF, _("Off")


def _protections(states: dict) -> tuple[str, str]:
    reduced = [
        states.get("performance/meltdownMitigations.sh"),
        states.get("performance/noWatchdog.sh"),
    ]
    if all(state is None for state in reduced):
        return HIDDEN, ""
    if any(reduced):
        return WARNING, _("Reduced")
    return ON, _("Default")


def _idle(states: dict) -> tuple[str, str]:
    at_20 = states.get("sleep/suspend-at-20.sh")
    battery = states.get("sleep/never-suspend-battery.sh")
    ac = states.get("sleep/never-suspend-ac.sh")
    if at_20 is None and battery is None and ac is None:
        return HIDDEN, ""
    if at_20:
        return ON, _("Suspends at 20% battery")
    if battery and ac:
        return ON, _("Stays awake")
    if battery:
        return ON, _("Stays awake on battery")
    if ac:
        return ON, _("Stays awake when plugged in")
    return OFF, _("System default")


def card_specs() -> list[CardSpec]:
    """Built at runtime so the titles are translated."""
    return [
        CardSpec("ssh", _("Remote access"), "ssh-symbolic", "blue", "system",
                 "sshStart", ("system/sshStart.sh",), _ssh),
        CardSpec("profile", _("Performance profile"), "performance-symbolic",
                 "orange", "performance", "cpuMaximumPerformance",
                 ("performance/cpuMaximumPerformance.sh",), _profile),
        CardSpec("idle", _("When idle"), "sleep-symbolic", "green", "sleep",
                 "never-suspend-battery",
                 ("sleep/suspend-at-20.sh", "sleep/never-suspend-battery.sh",
                  "sleep/never-suspend-ac.sh"), _idle),
        CardSpec("ai", _("Local AI"), "ollama-symbolic", "purple", "ai",
                 "ollamaCpu", _OLLAMA, _local_ai),
        CardSpec("docker", _("Docker"), "docker-symbolic", "teal", "apps",
                 "dockerEnable", ("docker/dockerEnable.sh",), _docker),
        CardSpec("protections", _("System protections"),
                 "meltdown-mitigations-symbolic", "red", "performance",
                 "meltdownMitigations",
                 ("performance/meltdownMitigations.sh",
                  "performance/noWatchdog.sh"), _protections),
    ]


class HomePage(BaseSettingsPage):
    def __init__(self, main_window, **kwargs):
        super().__init__(main_window, **kwargs)
        content = self.create_scrolled_content(
            _("Welcome"),
            _("Adjust BigLinux simply and safely. Here is how this computer is set up."),
        )

        self.flowbox = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            homogeneous=True,
            min_children_per_line=1,
            max_children_per_line=3,
            column_spacing=12,
            row_spacing=12,
        )
        self.flowbox.add_css_class("home-cards")
        content.append(self.flowbox)

        self.specs = card_specs()
        self.cards: dict[str, dict] = {}
        for spec in self.specs:
            self.cards[spec.card_id] = self._build_card(spec)

        tip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        tip.add_css_class("home-tip")
        tip_icon = Gtk.Image.new_from_icon_name("edit-find-symbolic")
        tip.append(tip_icon)
        tip_label = Gtk.Label(
            label=_(
                "Tip: search with everyday words, like “don't sleep” or “remote access”."
            ),
            xalign=0,
            wrap=True,
            hexpand=True,
        )
        tip.append(tip_label)
        content.append(tip)

        self._refresh_generation = 0

    def _build_card(self, spec: CardSpec) -> dict:
        button = Gtk.Button()
        button.add_css_class("card")
        button.add_css_class("home-card")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(14)
        box.set_margin_bottom(14)
        box.set_margin_start(14)
        box.set_margin_end(14)

        tile = Gtk.Box(halign=Gtk.Align.START)
        tile.add_css_class("home-card-icon")
        tile.add_css_class(f"tile-{spec.color}")
        # The app's own icons first: a theme may ship a different icon under
        # the same name (e.g. sleep-symbolic)
        icon_path = os.path.join(ICONS_DIR, f"{spec.icon}.svg")
        if os.path.exists(icon_path):
            image = Gtk.Image.new_from_gicon(Gio.FileIcon.new(Gio.File.new_for_path(icon_path)))
        else:
            image = Gtk.Image.new_from_icon_name(spec.icon)
        image.set_pixel_size(20)
        tile.append(image)
        box.append(tile)

        title = Gtk.Label(label=spec.title, xalign=0, wrap=True)
        title.add_css_class("heading")
        box.append(title)

        state = Gtk.Label(label=_("Checking…"), xalign=0, wrap=True)
        state.add_css_class("dim-label")
        state.add_css_class("caption")
        box.append(state)

        button.set_child(box)
        button.connect(
            "clicked",
            lambda _b: self.main_window.open_setting(spec.page_id, spec.target_script),
        )
        button.update_property(
            [Gtk.AccessibleProperty.LABEL], [f"{spec.title}: {_('Checking…')}"]
        )
        self.flowbox.append(button)
        child = button.get_parent()  # the Gtk.FlowBoxChild
        if child is not None:
            child.set_focusable(False)
        return {"button": button, "state": state, "spec": spec}

    # The home page has no switches: "sync" means refreshing the cards.
    def sync_all_switches_async(self, on_done: Optional[Callable] = None) -> None:
        self.refresh()
        if on_done is not None:
            GLib.idle_add(lambda: (on_done(), False)[1])

    def refresh(self) -> None:
        """Query every card's scripts in the background and update the cards."""
        self._refresh_generation += 1
        generation = self._refresh_generation
        scripts = sorted({s for spec in self.specs for s in spec.scripts})

        def _worker():
            try:
                with ThreadPoolExecutor(max_workers=min(4, len(scripts))) as pool:
                    results = dict(zip(scripts, pool.map(self.check_script_state, scripts)))
            except Exception:
                logger.exception("Failed to refresh the home cards")
                return
            states = {
                path: (None if status in (None, "true_disabled", STATUS_ERROR) else status)
                for path, (status, _message) in results.items()
            }
            GLib.idle_add(self._apply_states, generation, states)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_states(self, generation: int, states: dict) -> bool:
        if generation != self._refresh_generation:
            return False
        for card in self.cards.values():
            spec = card["spec"]
            kind, text = spec.describe({s: states.get(s) for s in spec.scripts})
            self.set_card_state(card, kind, text)
        return False

    @staticmethod
    def set_card_state(card: dict, kind: str, text: str) -> None:
        button, label = card["button"], card["state"]
        child = button.get_parent()
        visible = kind != HIDDEN
        (child or button).set_visible(visible)
        if not visible:
            return
        label.set_label(text)
        for css in ("state-on", "state-off", "state-warning"):
            label.remove_css_class(css)
        label.add_css_class(f"state-{kind}")
        if kind == WARNING:
            label.remove_css_class("dim-label")
        else:
            label.add_css_class("dim-label")
        button.update_property(
            [Gtk.AccessibleProperty.LABEL], [f"{card['spec'].title}: {text}"]
        )
