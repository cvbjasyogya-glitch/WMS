(function () {
    const body = document.body;
    const openButton = document.querySelector("[data-sidebar-open]");
    const closeButton = document.querySelector("[data-sidebar-close]");
    const sidebar = document.getElementById("appSidebar");

    function setSidebar(open) {
        if (!body || !sidebar) {
            return;
        }
        body.classList.toggle("sidebar-open", open);
    }

    openButton?.addEventListener("click", () => setSidebar(true));
    closeButton?.addEventListener("click", () => setSidebar(false));

    document.addEventListener("click", (event) => {
        if (!body.classList.contains("sidebar-open")) {
            return;
        }
        const target = event.target;
        if (!(target instanceof HTMLElement)) {
            return;
        }
        if (sidebar.contains(target) || openButton?.contains(target)) {
            return;
        }
        setSidebar(false);
    });

    window.addEventListener("resize", () => {
        if (window.innerWidth > 960) {
            setSidebar(false);
        }
    });
})();
