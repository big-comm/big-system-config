from base_page import BaseSettingsPage, _

OLLAMA_ICON = "ollama-symbolic"


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
