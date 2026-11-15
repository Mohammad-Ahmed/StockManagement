function addSizeRow() {
    const template = document.getElementById("sizeTemplate");
    const rows = document.getElementById("sizeRows");

    if (template && rows) {
        rows.appendChild(template.content.cloneNode(true));
    }
}

document.addEventListener("click", function (event) {
    if (!event.target.closest(".dropdown")) {
        document.querySelectorAll(".dropdown-menu").forEach(
            function (menu) {
                menu.classList.remove("show");
            }
        );
    }
});
