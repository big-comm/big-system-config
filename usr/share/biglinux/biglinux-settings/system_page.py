from base_page import BaseSettingsPage, _


class SystemPage(BaseSettingsPage):
    def __init__(self, main_window, **kwargs):
        super().__init__(main_window, **kwargs)

        local_ip = self.get_local_ip()

        content = self.create_scrolled_content(
            _("System"), _("Startup, disks and remote access.")
        )

        ## GROUP: Remote access ##
        remote = self.create_group(_("Remote access"), None, "system")
        content.append(remote)

        # sshStart (runs sshd now) + sshEnable (starts it at boot)
        ssh = self.create_row(
            remote,
            _("Remote terminal access (SSH)"),
            _(
                "Lets other computers open a terminal on this one. Stays on until "
                "turned off or the computer restarts."
            ),
            "sshStart",
            "ssh-symbolic",
            info_text=_("SSH Address: {}").format(local_ip),
            keywords=[_("remote access"), _("SSH"), _("terminal")],
        )
        self.create_sub_row(
            remote,
            _("Start automatically"),
            _("Turn on remote terminal access every time the computer starts."),
            "sshEnable",
            None,
            ssh,
            keywords=[_("remote access"), _("SSH")],
        )

        ## GROUP: Startup ##
        startup = self.create_group(_("Startup"), None, "system")
        content.append(startup)

        # fastGrub
        self.create_row(
            startup,
            _("Shorter boot menu wait"),
            _("Shows the boot menu for less time before starting the system."),
            "fastGrub",
            "grub-symbolic",
            recommended=True,
            keywords=[_("boot"), _("GRUB")],
            applies_after_restart=True,
        )

        # plymouthBootMessages
        self.create_row(
            startup,
            _("Show boot messages"),
            _("Shows system messages below the boot animation while the computer starts."),
            "plymouthBootMessages",
            "system-symbolic",
            timeout=240,
            keywords=[_("boot"), _("splash")],
            applies_after_restart=True,
        )

        ## GROUP: Disks ##
        disks = self.create_group(_("Disks"), None, "system")
        content.append(disks)

        # bigMount
        self.create_row(
            disks,
            _("Mount internal disks at startup"),
            _(
                "Makes the partitions of the internal disks available automatically "
                "when the computer starts."
            ),
            "bigMount",
            "bigmount-symbolic",
            keywords=[_("partitions"), _("auto-mount")],
        )
