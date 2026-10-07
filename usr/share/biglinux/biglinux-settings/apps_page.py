from base_page import BaseSettingsPage, _


class AppsPage(BaseSettingsPage):
    def __init__(self, main_window, **kwargs):
        super().__init__(main_window, **kwargs)

        self._local_ip = self.get_local_ip()

        content = self.create_scrolled_content(
            _("Apps & Services"), _("Install and manage services and developer tools.")
        )

        ## GROUP: Docker ##
        docker_group = self.create_group(_("Docker"), None, "docker")
        content.append(docker_group)

        self.create_row(
            docker_group,
            _("Docker"),
            _(
                "Container engine needed by all the services below. Installs Docker if it is missing; turning it off stops it."
            ),
            "dockerEnable",
            "docker-symbolic",
            keywords=[_("containers"), _("Docker")],
        )

        ## GROUP: Media & Cloud ##
        media = self.create_group(
            _("Media & Cloud"),
            _("Media servers and cloud storage. Require Docker."),
            "docker",
        )
        content.append(media)

        self._add_container(
            media,
            _("Nextcloud Plus"),
            _(
                "Cloud storage for your files, calendar and contacts. Installs it as a container; turning it off removes it."
            ),
            _("Start Nextcloud Plus"),
            _("Runs the Nextcloud Plus container."),
            "nextcloud-plus",
            _(
                "Nextcloud Plus is running.\nAddress: http://localhost:8286\nand\nAddress: http://{}:8286"
            ),
            [_("cloud"), _("Nextcloud")],
        )
        self._add_container(
            media,
            _("Jellyfin"),
            _(
                "Media server for your movies, series and music. Installs it as a container; turning it off removes it."
            ),
            _("Start Jellyfin"),
            _("Runs the Jellyfin container."),
            "jellyfin",
            _(
                "Jellyfin is running.\nAddress: http://localhost:8096\nand\nAddress: http://{}:8096"
            ),
            [_("media server"), _("Jellyfin")],
        )

        ## GROUP: Network & Security ##
        network = self.create_group(
            _("Network & Security"),
            _("Network tools and security services. Require Docker."),
            "docker",
        )
        content.append(network)

        self._add_container(
            network,
            _("AdGuard"),
            _(
                "AdGuard Home: blocks ads and trackers for the whole network through DNS. Installs it as a container; turning it off removes it."
            ),
            _("Start AdGuard"),
            _("Runs the AdGuard container."),
            "adguard",
            _(
                "AdGuard is running.\nAddress: http://localhost:3030\nand\nAddress: http://{}:3030"
            ),
            [_("ad blocker"), _("DNS"), _("AdGuard")],
        )
        self._add_container(
            network,
            _("V2RayA"),
            _(
                "Network proxy client with a web interface. Installs it as a container; turning it off removes it."
            ),
            _("Start V2RayA"),
            _("Runs the V2RayA container."),
            "v2raya",
            _(
                "V2RayA is running.\nAddress: http://localhost:2017\nand\nAddress: http://{}:2017"
            ),
            [_("proxy"), _("V2RayA")],
        )

        ## GROUP: Development & Tools ##
        dev = self.create_group(
            _("Development & Tools"),
            _("Development stacks and utility services. Require Docker."),
            "docker",
        )
        content.append(dev)

        self._add_container(
            dev,
            _("LAMP"),
            _(
                "Web development stack with Linux, Apache, MySQL and PHP. Installs it as a container; turning it off removes it."
            ),
            _("Start LAMP"),
            _("Runs the LAMP container."),
            "lamp",
            _(
                "LAMP is running.\nAddress: http://localhost:8080\nand\nAddress: http://{}:8080"
            ),
            [_("web server"), _("PHP"), _("MySQL")],
        )
        self._add_container(
            dev,
            _("Portainer Client"),
            _(
                "Portainer Agent, to manage this computer's containers from a Portainer server. Installs it as a container; turning it off removes it."
            ),
            _("Start Portainer Client"),
            _("Runs the Portainer Client container."),
            "portainer-client",
            _(
                "Portainer Client is running.\nAddress: http://localhost:9000\nand\nAddress: http://{}:9000"
            ),
            [_("Portainer"), _("cluster")],
        )
        self._add_container(
            dev,
            _("SWS"),
            _(
                "Static Web Server, to publish static websites. Installs it as a container; turning it off removes it."
            ),
            _("Start SWS"),
            _("Runs the SWS container."),
            "sws",
            _(
                "SWS is running.\nAddress: http://localhost:8182\nand\nAddress: http://{}:8182"
            ),
            [_("web server"), _("static")],
        )
        self._add_container(
            dev,
            _("Open Notebook"),
            _(
                "Open-source alternative to Google's NotebookLM. Installs it as a container; turning it off removes it."
            ),
            _("Open Notebook Server"),
            _("Start the Open Notebook server."),
            "openNotebook",
            _(
                "Open Notebook is running.\nAddress: http://localhost:8502\nand\nAddress: http://{}:8502"
            ),
            [_("NotebookLM"), _("AI")],
            icon="openNotebook-symbolic",
        )

        ## GROUP: Developer tools (script group "developer") ##
        developer = self.create_group(
            _("Developer tools"),
            _("Coding agents and command-line tools for developers."),
            "developer",
        )
        content.append(developer)

        # OpenClaude — open-source coding agent CLI (200+ models via OpenAI-compat)
        link_openclaude = "https://github.com/Gitlawb/openclaude"
        self.create_row(
            developer,
            _("OpenClaude"),
            _(
                "Open-source coding-agent CLI for OpenAI, Gemini, DeepSeek, Ollama and 200+ models. Installs it with nodejs, npm and ripgrep as dependencies; turning it off removes it."
            ),
            "openclaude",
            "openclaude-symbolic",
            timeout=600,
            link_url=link_openclaude,
            keywords=[_("coding agent"), _("AI"), _("programming")],
        )

    def _add_container(
        self,
        group,
        title,
        description,
        run_title,
        run_subtitle,
        script_key,
        running_info,
        keywords,
        icon=None,
    ):
        """Row that installs a container (<key>Install.sh) plus its sub-row
        that runs it (<key>Run.sh)."""
        icon = icon or f"docker-{script_key}-symbolic"
        installed = self.create_row(
            group,
            title,
            description,
            f"{script_key}Install",
            icon,
            keywords=keywords,
        )
        self.create_sub_row(
            group,
            run_title,
            run_subtitle,
            f"{script_key}Run",
            icon,
            installed,
            info_text=running_info.format(self._local_ip),
        )
