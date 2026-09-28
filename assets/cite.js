/* "Cite this page": fills in today's date as the access date, and adds a
   button that copies the citation. Without JavaScript the citation reads
   "accessed [date]" and can be copied by hand. */

(function () {
  "use strict";

  document.querySelectorAll("[data-cite-text]").forEach(function (text) {
    var date = text.querySelector("[data-cite-date]");
    if (date) {
      date.textContent = new Date().toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
    }

    if (!navigator.clipboard) return;
    var button = document.createElement("button");
    button.type = "button";
    button.textContent = "Copy citation";
    var status = document.createElement("span");
    status.setAttribute("role", "status");
    status.className = "cite-status";
    var actions = document.createElement("p");
    actions.className = "cite-actions";
    actions.appendChild(button);
    actions.appendChild(status);
    text.parentNode.insertBefore(actions, text.nextSibling);

    button.addEventListener("click", function () {
      navigator.clipboard.writeText(text.textContent.replace(/\s+/g, " ").trim()).then(
        function () { status.textContent = "Copied."; },
        function () { status.textContent = "Couldn't copy. Select the text and copy it instead."; }
      );
    });
  });
})();
