from base_page import BaseSettingsPage, _

OLLAMA_ICON = "ollama-symbolic"


class AIPage(BaseSettingsPage):
    def __init__(self, main_window, **kwargs):
        super().__init__(main_window, **kwargs)

        local_ip = self.get_local_ip()

        # Create the container (base method)
        content = self.create_scrolled_content()

        # Create the AI Interfaces group
        aiGui = self.create_group(
            _("AI Interfaces"),
            _("Graphical interface for artificial intelligence."),
            "ai",
        )
        content.append(aiGui)

        # Create the group Ollama (base method)
        ollamaServer = self.create_group(
            _("Ollama Server"),
            _("Choose which Ollama server is best for your hardware."),
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
        )

        # ExpanderRow to collapse the 4 Ollama variants
        ollama_expander = self.create_expander_row(
            ollamaServer,
            _("Ollama Variants"),
            _("Select the variant that matches your GPU hardware."),
            OLLAMA_ICON,
        )

        # ChatAI
        self.create_row(
            aiGui,
            _("ChatAI"),
            _("A variety of chats like Plasmoid for your KDE Plasma desktop."),
            "chatai",
            "chatai-symbolic",
        )
        # Ollama LAB
        self.create_row(
            aiGui,
            _("Ollama LAB"),
            _("Graphical interface for managing Ollama models and chat."),
            "ollamaLab",
            OLLAMA_ICON,
        )
        # ChatBox
        self.create_row(
            aiGui,
            _("ChatBox"),
            _("User-friendly Desktop Client App for AI Models/LLMs."),
            "chatbox",
            "chatbox-symbolic",
        )
        # LM Studio
        self.create_row(
            aiGui,
            _("LM Studio"),
            _(
                "LM Studio - A desktop app for exploring and running large language models locally."
            ),
            "lmStudio",
            "lmstudio-symbolic",
        )
        # Open Notebook (requires Docker)
        openNotebook = self.create_row(
            aiGui,
            _("Open Notebook"),
            _(
                "Open-source, privacy-focused alternative to Google's NotebookLM. Requires Docker enabled."
            ),
            "openNotebookInstall",
            "openNotebook-symbolic",
        )
        self.create_sub_row(
            aiGui,
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
            aiGui,
            _("ComfyUI (GPU ONLY)"),
            _("The most powerful and modular visual AI engine and application."),
            "comfyUI",
            "comfyUI-symbolic",
            timeout=1200,
            link_url=link_comfyui,
        )
        self.create_sub_row(
            aiGui,
            _("ComfyUI Server"),
            _("Start the ComfyUI server."),
            "comfyUIRun",
            "comfyUI-symbolic",
            comfyUI,
            info_text=_(
                "ComfyUI server is running.\nAddress: http://localhost:8188\nand\nAddress: http://{}:8188"
            ).format(local_ip),
        )
        # Ollama variants (CPU, Vulkan, Nvidia CUDA, AMD ROCm), each with a
        # "Share Ollama" sub-row exposing the server on the local network.
        ollama_variants = (
            (
                _("OllamaCPU"),
                _("Local AI server. For CPUs only."),
                "ollamaCpu",
            ),
            (
                _("Ollama Vulkan"),
                _("Local AI server. For CPUs, AMD/Nvidia and integrated GPUs."),
                "ollamaVulkan",
            ),
            (
                _("Ollama Nvidia CUDA"),
                _(
                    "Local AI server. For newer Nvidia GPUs, starting from the 2000 series."
                ),
                "ollamaNvidia",
            ),
            (
                _("Ollama AMD ROCm"),
                _(
                    "Local AI server. For newer AMD GPUs, starting from the 6000 series.\nConsider using Vulkan, in many tests, Vulkan performed better than ROCm."
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
        )
        self.create_sub_row(
            expander,
            _("Share Ollama"),
            _("Share ollama on the local network."),
            "ollamaShare",
            OLLAMA_ICON,
            ollama,
            info_text=_("Ollama server is running.\nAddress: http://{}:11434").format(
                local_ip
            ),
        )
