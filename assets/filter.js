/* Client-side table filtering, as a progressive enhancement.
   Every row is already in the HTML; this only hides rows that don't match, so
   the pages work unchanged with JavaScript off. */

(function () {
  "use strict";

  document.querySelectorAll("[data-filter-form]").forEach(function (form) {
    var table = document.getElementById(form.dataset.target);
    if (!table) return;

    var rows = Array.prototype.slice.call(table.tBodies[0].rows);
    var count = form.parentNode.querySelector("[data-filter-count]");
    var text = form.querySelector("[data-filter-text]");
    var selects = Array.prototype.slice.call(form.querySelectorAll("[data-filter-select]"));
    var flags = Array.prototype.slice.call(form.querySelectorAll("[data-filter-flag]"));
    var noun = (count && /\b(agreements|organisations|datasets)\b/.exec(count.textContent) || [, "rows"])[1];
    var total = rows.length;
    var timer;

    form.addEventListener("submit", function (event) { event.preventDefault(); });

    function apply() {
      var terms = (text && text.value || "").toLowerCase().split(/\s+/).filter(Boolean);
      var shown = 0;

      rows.forEach(function (row) {
        var haystack = row.dataset.search || row.textContent.toLowerCase();
        var match = terms.every(function (term) { return haystack.indexOf(term) !== -1; });

        if (match) {
          match = selects.every(function (select) {
            return !select.value || row.dataset[select.dataset.key] === select.value;
          });
        }
        if (match) {
          match = flags.every(function (flag) {
            return !flag.checked || row.dataset[flag.dataset.key] === flag.value;
          });
        }

        row.hidden = !match;
        if (match) shown++;
      });

      if (count) {
        count.textContent = shown === total
          ? "Showing all " + total.toLocaleString("en-GB") + " " + noun + "."
          : "Showing " + shown.toLocaleString("en-GB") + " of " + total.toLocaleString("en-GB") + " " + noun + ".";
      }
    }

    // Debounce typing so a 2,000-row table stays responsive; react immediately
    // to the discrete controls.
    if (text) {
      text.addEventListener("input", function () {
        clearTimeout(timer);
        timer = setTimeout(apply, 150);
      });
    }
    selects.concat(flags).forEach(function (control) {
      control.addEventListener("change", apply);
    });

    var reset = form.querySelector("[data-filter-reset]");
    if (reset) {
      reset.addEventListener("click", function () {
        if (text) text.value = "";
        selects.forEach(function (select) { select.value = ""; });
        flags.forEach(function (flag) { flag.checked = false; });
        apply();
        if (text) text.focus();
      });
    }

    // Deep links like /agreements/?q=cancer prefill the search box.
    var query = new URLSearchParams(window.location.search).get("q");
    if (query && text) { text.value = query; }
    apply();
  });
})();
