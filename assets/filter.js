/* Client-side table filtering and sorting, as a progressive enhancement.
   Every row is already in the HTML; this only hides and reorders rows, so the
   pages work unchanged with JavaScript off. The state of the filters and the
   sort is kept in the query string, so a filtered view can be linked to. */

(function () {
  "use strict";

  // Writes one query-string parameter without adding a history entry; an empty
  // value removes it, so an unfiltered page keeps a clean URL.
  function setParam(name, value) {
    try {
      var url = new URL(window.location.href);
      if (value) url.searchParams.set(name, value); else url.searchParams.delete(name);
      window.history.replaceState(null, "", url);
    } catch (error) { /* file:// and sandboxed frames refuse; the page still works. */ }
  }

  var params = new URLSearchParams(window.location.search);

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

      if (text) setParam("q", text.value.trim());
      selects.forEach(function (select) { setParam(select.dataset.key, select.value); });
      flags.forEach(function (flag) { setParam(flag.dataset.key, flag.checked ? flag.value : ""); });
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

    // Restore the state a link carries: /agreements/?q=cancer&commercial=yes.
    if (text && params.get("q")) text.value = params.get("q");
    selects.forEach(function (select) {
      var wanted = params.get(select.dataset.key);
      // An option that no longer exists would leave the select blank while
      // still filtering on it, so only accept values the page offers.
      if (wanted && Array.prototype.some.call(select.options, function (o) { return o.value === wanted; })) {
        select.value = wanted;
      }
    });
    flags.forEach(function (flag) { flag.checked = params.get(flag.dataset.key) === flag.value; });
    apply();
  });

  // Sortable tables: a header button per column. The first click sorts a
  // number largest-first and anything else A to Z; the second reverses it; the
  // third restores the order the page came in. A cell can carry `data-sort` to
  // sort on something other than what it shows (a date shown as words).
  document.querySelectorAll("table.sortable").forEach(function (table) {
    var body = table.tBodies[0];
    var original = Array.prototype.slice.call(body.rows);
    var headers = Array.prototype.slice.call(table.tHead.rows[0].cells);
    var collator = new Intl.Collator("en-GB", { sensitivity: "base", numeric: true });

    function keyOf(header, index) {
      return header.textContent.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || String(index);
    }

    function value(row, index) {
      var cell = row.cells[index];
      if (!cell) return "";
      var raw = cell.dataset.sort !== undefined ? cell.dataset.sort : cell.textContent.trim();
      return raw === "—" ? "" : raw;
    }

    function sortBy(index, direction) {
      var numeric = headers[index].classList.contains("num");
      var sign = direction === "descending" ? -1 : 1;
      var ordered = direction ? original.slice().sort(function (a, b) {
        var x = value(a, index), y = value(b, index);
        // Blanks go last whichever way round, so a sort never opens on a page of dashes.
        if (!x || !y) return (x ? -1 : 0) + (y ? 1 : 0);
        var result = numeric
          ? parseFloat(x.replace(/,/g, "")) - parseFloat(y.replace(/,/g, ""))
          : collator.compare(x, y);
        return sign * result;
      }) : original;
      ordered.forEach(function (row) { body.appendChild(row); });
      headers.forEach(function (header, i) {
        if (i === index && direction) header.setAttribute("aria-sort", direction);
        else header.removeAttribute("aria-sort");
      });
      setParam("sort", direction ? keyOf(headers[index], index) : "");
      setParam("dir", direction === "descending" ? "desc" : "");
    }

    headers.forEach(function (header, index) {
      var button = document.createElement("button");
      button.type = "button";
      while (header.firstChild) button.appendChild(header.firstChild);
      header.appendChild(button);
      button.addEventListener("click", function () {
        var current = header.getAttribute("aria-sort");
        var first = header.classList.contains("num") ? "descending" : "ascending";
        var second = first === "descending" ? "ascending" : "descending";
        sortBy(index, current === first ? second : current === second ? null : first);
      });
    });

    var wanted = params.get("sort");
    if (wanted) {
      headers.forEach(function (header, index) {
        if (keyOf(header, index) === wanted) sortBy(index, params.get("dir") === "desc" ? "descending" : "ascending");
      });
    }
  });
})();
