/* Print every folded section. A closed <details> prints as its summary alone,
   which would leave a printed agreement without its purpose text; sections are
   opened for printing and put back as they were afterwards. */

(function () {
  "use strict";

  var opened = [];
  window.addEventListener("beforeprint", function () {
    document.querySelectorAll("details:not([open])").forEach(function (details) {
      details.open = true;
      opened.push(details);
    });
  });
  window.addEventListener("afterprint", function () {
    opened.forEach(function (details) { details.open = false; });
    opened = [];
  });
})();
