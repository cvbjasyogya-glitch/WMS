(function () {
    document.querySelectorAll("[data-password-toggle]").forEach((button) => {
        const field = button.closest(".password-field");
        const input = field?.querySelector("input[type='password'], input[type='text']");
        const icon = button.querySelector("i");

        if (!input) {
            return;
        }

        button.addEventListener("click", () => {
            const isVisible = input.type === "text";
            input.type = isVisible ? "password" : "text";
            button.setAttribute("aria-pressed", String(!isVisible));
            button.setAttribute("aria-label", isVisible ? "Lihat password" : "Sembunyikan password");

            if (icon) {
                icon.classList.toggle("bi-eye", isVisible);
                icon.classList.toggle("bi-eye-slash", !isVisible);
            }
        });
    });
})();
