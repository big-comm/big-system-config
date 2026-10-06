from base_page import BaseSettingsPage, _


class UsabilityPage(BaseSettingsPage):
    def __init__(self, main_window, **kwargs):
        super().__init__(main_window, **kwargs)

        content = self.create_scrolled_content(
            _("Appearance & Usage"), _("Windows, keyboard and recent files.")
        )

        ## GROUP: Keyboard ##
        keyboard = self.create_group(_("Keyboard"), None, "usability")
        content.append(keyboard)

        # numLock
        self.create_row(
            keyboard,
            _("Numeric keypad on at login"),
            _(
                "Turns Num Lock on at the login screen. Has no effect with automatic login."
            ),
            "numLock",
            "numlock-symbolic",
            keywords=[_("Num Lock"), _("NumLock")],
        )

        # keyboardLed
        self.create_row(
            keyboard,
            _("Keyboard Light"),
            _(
                "Keep the keyboard backlight on. For keyboards whose light is controlled by the Scroll Lock LED."
            ),
            "keyboardLed",
            "keyboard-led-symbolic",
            keywords=[_("backlight"), _("Scroll Lock")],
        )

        ## GROUP: Windows ##
        windows = self.create_group(_("Windows"), None, "usability")
        content.append(windows)

        # windowButtonOnLeftSide
        self.create_row(
            windows,
            _("Window buttons on the left"),
            _("Shows the close, minimize and maximize buttons on the left side of windows."),
            "windowButtonOnLeftSide",
            "window-controls-symbolic",
            keywords=[_("close button"), _("title bar")],
        )

        # KZones
        self.create_row(
            windows,
            _("Window snapping zones (KZones)"),
            _(
                "Lets you drag windows into predefined screen zones to arrange them side by side. Installs KZones if it is missing."
            ),
            "kzones",
            "kzones-symbolic",
            keywords=[_("tiling"), _("KZones")],
        )

        ## GROUP: Files ##
        files = self.create_group(_("Files"), None, "usability")
        content.append(files)

        # Recent Files & Locations
        self.create_row(
            files,
            _("Show recent files and folders"),
            _(
                "Remembers recently opened files and folders in the file manager and the application menu. On KDE Plasma, turning it off also clears the current list."
            ),
            "recentFiles",
            "recent_files-symbolic",
            keywords=[_("recent"), _("history"), _("privacy")],
        )
