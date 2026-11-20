import logging
import os

from base_page import BaseSettingsPage, _
from gi.repository import Adw, Gio, GLib

logger = logging.getLogger("biglinux-settings")

OLLAMA_ICON = "ollama-symbolic"

AUR_PACKAGES = {
    "chatbox.sh": "chatbox-bin",
    "lmStudio.sh": "lmstudio-bin",
    "ollamaLab.sh": "ollama-lab-bin",
}


class AIPage(BaseSettingsPage):
    def __init__(self, main_window, **kwargs):
        super().__init__(main_window, **kwargs)

        local_ip = self.get_local_ip()

        content = self.create_scrolled_content(
            _("Artificial Intelligence"),
            _("Chat, work with documents and create images with AI on this computer."),
        )

        ai_keywords = [_("chat"), _("local AI"), _("LLM")]

        ## GROUP: AI applications ##
        apps = self.create_group(
            _("AI applications"),
            None,
            "ai",
        )
        content.append(apps)

        # ChatAI
        self.create_row(
            apps,
            _("ChatAI"),
            _(
                "Desktop widget with access to several AI chats for KDE Plasma. Installs the widget; turning it off removes it."
            ),
            "chatai",
            "chatai-symbolic",
            keywords=ai_keywords + [_("widget"), _("plasmoid")],
        )
        # Ollama LAB
        self.create_row(
            apps,
            _("Ollama LAB"),
            _(
                "Graphical app to manage Ollama models and chat with them. Installs Ollama LAB; turning it off removes it."
            ),
            "ollamaLab",
            OLLAMA_ICON,
            keywords=ai_keywords + [_("Ollama")],
        )
        # ChatBox
        self.create_row(
            apps,
            _("ChatBox"),
            _(
                "Desktop app to chat with AI models, local or online. Installs ChatBox; turning it off removes it."
            ),
            "chatbox",
            "chatbox-symbolic",
            keywords=ai_keywords,
        )
        # LM Studio
        self.create_row(
            apps,
            _("LM Studio"),
            _(
                "Desktop app to download and run language models on this computer. Installs LM Studio; turning it off removes it."
            ),
            "lmStudio",
            "lmstudio-symbolic",
            keywords=ai_keywords,
        )
        # Open Notebook (requires Docker)
        openNotebook = self.create_row(
            apps,
            _("Open Notebook"),
            _(
                "Open-source, privacy-focused alternative to Google's NotebookLM for working with your documents. Installs it as a container and requires Docker; turning it off removes it."
            ),
            "openNotebookInstall",
            "openNotebook-symbolic",
            keywords=ai_keywords + [_("documents"), _("NotebookLM")],
        )
        self.create_sub_row(
            apps,
            _("Open Notebook Server"),
            _("Start the Open Notebook server."),
            "openNotebookRun",
            "openNotebook-symbolic",
            openNotebook,
            info_text=_(
                "Open Notebook is running.\nAddress: http://localhost:8502\nand\nAddress: http://{}:8502"
            ).format(local_ip),
        )
        # ComfyUI
        link_comfyui = "https://github.com/Comfy-Org/ComfyUI"
        comfyUI = self.create_row(
            apps,
            _("ComfyUI image generation"),
            _(
                "Create images with AI using a visual node editor. Requires an AMD or Nvidia graphics card. Installs ComfyUI in your home folder; turning it off removes it."
            ),
            "comfyUI",
            "comfyUI-symbolic",
            timeout=1200,
            link_url=link_comfyui,
            keywords=[_("images"), _("Stable Diffusion"), _("local AI")],
        )
        self.create_sub_row(
            apps,
            _("ComfyUI Server"),
            _("Start the ComfyUI server."),
            "comfyUIRun",
            "comfyUI-symbolic",
            comfyUI,
            info_text=_(
                "ComfyUI server is running.\nAddress: http://localhost:8188\nand\nAddress: http://{}:8188"
            ).format(local_ip),
        )

        ## GROUP: Ollama server ##
        ollamaServer = self.create_group(
            _("Ollama Server"),
            _(
                "Ollama runs AI models on this computer. The variants below are alternative engines for different hardware: install only the one that matches your processor or graphics card."
            ),
            "ai",
        )
        content.append(ollamaServer)

        # Action: update installed Ollama variants
        self.create_action_row(
            ollamaServer,
            _("Update Ollama"),
            _("Update the installed Ollama packages to the latest version."),
            "ollamaUpdate",
            OLLAMA_ICON,
            action_label=_("Update now"),
            timeout=1800,
            keywords=[_("Ollama"), _("local AI")],
        )

        ollama_expander = self.create_expander_row(
            ollamaServer,
            _("Ollama Variants"),
            _("Select the variant that matches your hardware."),
            OLLAMA_ICON,
        )

        # Ollama variants (CPU, Vulkan, Nvidia CUDA, AMD ROCm), each with a
        # "Share Ollama" sub-row exposing the server on the local network.
        ollama_variants = (
            (
                _("Ollama for CPU"),
                _(
                    "Runs AI models on the processor only. Installs Ollama; turning it off removes it."
                ),
                "ollamaCpu",
            ),
            (
                _("Ollama Vulkan"),
                _(
                    "For processors, AMD and Nvidia graphics cards and integrated graphics. Installs Ollama; turning it off removes it."
                ),
                "ollamaVulkan",
            ),
            (
                _("Ollama Nvidia CUDA"),
                _(
                    "For newer Nvidia graphics cards, from the 2000 series on. Installs Ollama; turning it off removes it."
                ),
                "ollamaNvidia",
            ),
            (
                _("Ollama AMD ROCm"),
                _(
                    "For newer AMD graphics cards, from the 6000 series on. In many tests Vulkan performed better than ROCm. Installs Ollama; turning it off removes it."
                ),
                "ollamaAmd",
            ),
        )
        for title, subtitle, script_key in ollama_variants:
            self._add_ollama_variant(
                ollama_expander, title, subtitle, script_key, local_ip
            )
        self.main_window.connect("notify::is-active", self._refresh_after_external_install)

    def _refresh_after_external_install(self, window, _property):
        if window.is_active() and self.get_mapped():
            self.sync_all_switches_async()

    def _execute_toggle(self, switch, state):
        execute_native = super()._execute_toggle
        script_name = os.path.basename(self.switch_scripts.get(switch, ""))
        package = AUR_PACKAGES.get(script_name)
        if not state or package is None:
            return execute_native(switch, state)

        flags = Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_PIPE
        launcher = Gio.SubprocessLauncher.new(flags)
        launcher.setenv("LC_ALL", "C", True)
        try:
            query = launcher.spawnv(["pacman", "-Si", "--", package])
        except GLib.Error:
            return execute_native(switch, state)

        row = self._get_wd(switch, "row")
        row.set_sensitive(False)
        self._busy_switches.add(switch)

        def on_package_checked(process, result):
            self._busy_switches.discard(switch)
            row.set_sensitive(True)
            try:
                _, _, stderr = process.communicate_utf8_finish(result)
            except GLib.Error:
                execute_native(switch, state)
                return

            # Database errors must go through the normal toggle error path.
            if (
                process.get_if_exited()
                and process.get_exit_status() == 1
                and (stderr or "").strip() == f"error: package '{package}' was not found"
            ):
                self._set_switch_active_without_handler(switch, False)
                self._offer_aur_install(package)
            else:
                execute_native(switch, state)

        query.communicate_utf8_async(None, None, on_package_checked)

    def _offer_aur_install(self, package):
        terminal = GLib.find_program_in_path("xdg-terminal-exec")
        helper = GLib.find_program_in_path("yay")
        if os.geteuid() == 0 or not terminal or not helper:
            self._show_info_dialog(
                _("Package available in the AUR"),
                _("Install {} with a package manager that supports the AUR.").format(package),
            )
            return

        dialog = Adw.AlertDialog(
            heading=_("Package available in the AUR"),
            body=_(
                "{} is available from the community-maintained Arch User Repository. "
                "Open a terminal to review and confirm the installation."
            ).format(package),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("install", _("Open terminal"))
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response):
            if response != "install":
                return
            try:
                terminal_process = Gio.Subprocess.new(
                    [terminal, "--hold", "--", helper, "-S", "--aur", "--needed", "--", package],
                    Gio.SubprocessFlags.NONE,
                )
                terminal_process.wait_check_async(None, on_terminal_exit)
            except GLib.Error as error:
                report_terminal_error(error)

        def on_terminal_exit(process, result):
            try:
                process.wait_check_finish(result)
            except GLib.Error as error:
                report_terminal_error(error)
            self.sync_all_switches_async()

        def report_terminal_error(error):
            logger.error("AUR terminal exited unsuccessfully for %s: %s", package, error)
            self.main_window.show_toast(
                _("Could not complete the AUR installation for {}.").format(package)
            )

        dialog.connect("response", on_response)
        dialog.present(self.main_window)

    def _add_ollama_variant(self, expander, title, subtitle, script_key, local_ip):
        """Add an Ollama server row plus its "Share Ollama" sub-row."""
        ollama = self.create_row(
            expander,
            title,
            subtitle,
            script_key,
            OLLAMA_ICON,
            info_text=_("Ollama server is running.\nAddress: http://localhost:11434"),
            keywords=[_("Ollama"), _("local AI"), _("LLM")],
        )
        self.create_sub_row(
            expander,
            _("Share Ollama"),
            _("Lets other computers on the local network use this Ollama server."),
            "ollamaShare",
            OLLAMA_ICON,
            ollama,
            info_text=_("Ollama server is running.\nAddress: http://{}:11434").format(
                local_ip
            ),
        )
