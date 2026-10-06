from base_page import BaseSettingsPage, _


class PerformancePage(BaseSettingsPage):
    def __init__(self, main_window, **kwargs):
        super().__init__(main_window, **kwargs)

        content = self.create_scrolled_content(
            _("Performance"), _("Balance speed, power use and stability.")
        )

        ## GROUP: Power profile ##
        power = self.create_group(_("Power profile"), None, "performance")
        content.append(power)

        self.create_row(
            power,
            _("Performance profile"),
            _(
                "Prioritizes performance. May increase power use, temperature and fan noise. Turning it off restores the previous profile."
            ),
            "cpuMaximumPerformance",
            "cpu-maximum-performance-symbolic",
            keywords=[_("speed"), _("CPU"), _("power profile")],
        )

        ## GROUP: Desktop ##
        desktop = self.create_group(_("Desktop"), None, "performance")
        content.append(desktop)

        # disableVisualEffects: script "true" = effects disabled
        self.create_row(
            desktop,
            _("Visual effects"),
            _(
                "Blur, shadows and animations of the desktop. Turning them off makes the interface plainer and can help on computers with slow graphics."
            ),
            "disableVisualEffects",
            "disable-visual-effects-symbolic",
            keywords=[_("animations"), _("blur"), _("effects")],
            inverted=True,
        )
        # disableBalooIndexer: script "true" = indexer disabled
        self.create_row(
            desktop,
            _("File indexing"),
            _(
                "Lets Dolphin and the application menu find files quickly by name and content. Turning it off saves disk and processor use, but that search no longer finds files quickly."
            ),
            "disableBalooIndexer",
            "disable-baloo-indexer-symbolic",
            keywords=[_("Baloo"), _("search"), _("indexer")],
            inverted=True,
        )

        ## GROUP: Application launch (script group "preload") ##
        preload = self.create_group(
            _("Application launch"),
            _(
                "Keeps selected applications ready in memory so they open faster. Uses more memory."
            ),
            "preload",
        )
        content.append(preload)

        # The preload script reports "unsupported" when the app is not installed
        preload_apps = (
            (_("Firefox"), "firefox", "firefox-symbolic"),
            (_("Brave"), "brave", "brave-symbolic"),
            (_("Chrome"), "chrome", "chrome-symbolic"),
            (_("Chromium"), "chromium", "chromium-symbolic"),
            (_("LibreWolf"), "librewolf", "librewolf-symbolic"),
            (_("Pale Moon"), "palemoon", "palemoon-symbolic"),
            (_("Opera"), "opera", "opera-symbolic"),
            (_("Vivaldi"), "vivaldi", "preload-symbolic"),
            (_("GNOME Web"), "epiphany", "preload-symbolic"),
            (_("LibreOffice"), "libreoffice", "libreoffice-symbolic"),
        )
        for label, script, icon in preload_apps:
            self.create_row(
                preload,
                label,
                None,
                script,
                icon,
                keywords=[_("open programs faster"), _("preload")],
            )

        ## GROUP: Protections and diagnostics ##
        protections = self.create_group(
            _("Protections and diagnostics"),
            _("Advanced. These options reduce protections or monitoring of the system."),
            "performance",
        )
        content.append(protections)

        # unloadSmartMonitor: script "true" = smartd stopped
        self.create_row(
            protections,
            _("Disk health monitoring"),
            _(
                "Keeps the S.M.A.R.T. service watching disks for signs of failure. Installs smartmontools if it is missing."
            ),
            "unloadSmartMonitor",
            "unload-smart-monitor-symbolic",
            keywords=[_("SMART"), _("smartd"), _("disk")],
            inverted=True,
        )
        # Meltdown mitigations
        link_meltdown = "https://meltdownattack.com"
        self.create_dangerous_row(
            protections,
            _("Turn off CPU vulnerability protections"),
            _(
                "Adds mitigations=off to the kernel command line, disabling the protections against Spectre, Meltdown and similar processor flaws. Faster in some workloads, but less secure. Applies after restart."
            ),
            "meltdownMitigations",
            "meltdown-mitigations-symbolic",
            warning_message=_(
                "The kernel will stop protecting against processor flaws such as Spectre and Meltdown. Some workloads get faster, but malicious programs or web pages may be able to read data from other programs. The change applies after the next restart."
            ),
            confirm_label=_("Turn off protections"),
            link_url=link_meltdown,
            keywords=[_("mitigations"), _("Spectre"), _("Meltdown"), _("speed")],
            applies_after_restart=True,
        )
        # noWatchdog
        self.create_dangerous_row(
            protections,
            _("Turn off lockup detectors"),
            _(
                "Adds nowatchdog and tsc=nowatchdog to the kernel command line, disabling the kernel soft and hard lockup detectors and the TSC clocksource watchdog. Applies after restart."
            ),
            "noWatchdog",
            "watchdog-symbolic",
            warning_message=_(
                "The kernel will no longer detect and report processors that stop responding, and will no longer check the stability of the TSC clock. Freezes may go unreported and become harder to diagnose. The change applies after the next restart."
            ),
            confirm_label=_("Turn off detectors"),
            keywords=[_("watchdog"), _("nowatchdog")],
            applies_after_restart=True,
        )
