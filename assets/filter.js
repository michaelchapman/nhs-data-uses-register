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

  // The word index (pipeline/search.py): one file per first character, mapping
  // a word to the numbers of the agreements that use it. A search term under
  // four letters matches a whole word, so "ai" doesn't find "maintain"; a
  // longer one matches the start of a word, so "pharma" finds "pharmaceutical".
  function searchWords(value) {
    // Split as the index was built: apostrophes dropped, so "king's" is "kings".
    return (value || "").toLowerCase().replace(/['\u2019]/g, "").match(/[a-z0-9]+/g) || [];
  }

  // "x" and a hexadecimal bitset, or hexadecimal gaps between numbers.
  function decode(postings) {
    var numbers = [];
    if (postings.charAt(0) === "x") {
      for (var k = postings.length - 1, bit = 0; k > 0; k--, bit += 4) {
        var nibble = parseInt(postings.charAt(k), 16);
        for (var j = 0; j < 4; j++) if (nibble >> j & 1) numbers.push(bit + j);
      }
    } else {
      var previous = -1;
      postings.split(",").forEach(function (gap) { previous += parseInt(gap, 16); numbers.push(previous); });
    }
    return numbers;
  }

  // The agreement numbers matching one term, as {number: true}.
  function matching(term, shard) {
    var found = {};
    function add(word) { decode(shard[word]).forEach(function (n) { found[n] = true; }); }
    if (term.length < 4) {
      if (Object.prototype.hasOwnProperty.call(shard, term)) add(term);
    } else {
      Object.keys(shard).forEach(function (word) { if (word.lastIndexOf(term, 0) === 0) add(word); });
    }
    return found;
  }

  document.querySelectorAll("[data-filter-form]").forEach(function (form) {
    var table = document.getElementById(form.dataset.target);
    if (!table) return;

    var rows = Array.prototype.slice.call(table.tBodies[0].rows);
    var wrapper = table.closest(".table-scroll") || table;
    var count = form.parentNode.querySelector("[data-filter-count]");
    var text = form.querySelector("[data-filter-text]");
    var selects = Array.prototype.slice.call(form.querySelectorAll("[data-filter-select]"));
    var flags = Array.prototype.slice.call(form.querySelectorAll("[data-filter-flag]"));
    var noun = (count && /\b(agreements|organisations|datasets)\b/.exec(count.textContent) || [, "rows"])[1];
    var reset = form.querySelector("[data-filter-reset]");
    // "Clear filters", or "Reset filters" where a filter is on by default.
    var resetLabel = reset ? reset.textContent.trim().toLowerCase() : "clear filters";
    var total = rows.length;
    var timer;
    // Where this table's word index is, if it has one. Files are fetched when a
    // search needs them and kept; until they arrive, or if they can't be had,
    // the search falls back to the text each row carries in `data-search`.
    var indexUrl = form.dataset.searchIndex;
    var shards = {};
    var loading = {};
    var indexFailed = !indexUrl || !window.fetch;

    function load(key) {
      if (!loading[key]) {
        loading[key] = fetch(indexUrl + key + ".json")
          .then(function (response) {
            // No file means no word starts with this character.
            if (response.status === 404) return { words: {} };
            if (!response.ok) throw new Error(response.status);
            return response.json();
          })
          .then(function (data) { shards[key] = data.words; })
          .catch(function () { indexFailed = true; });
      }
      return loading[key];
    }

    // Row numbers matching every word searched for, as {number: true}; null to
    // search `data-search` instead; undefined while files are still loading.
    function indexed(value) {
      if (indexFailed) return null;
      var words = searchWords(value);
      if (!words.length) return null;
      var missing = words.map(function (w) { return w.charAt(0); })
        .filter(function (key, i, keys) { return !shards[key] && keys.indexOf(key) === i; });
      if (missing.length) {
        Promise.all(missing.map(load)).then(apply);
        return undefined;
      }
      return words.reduce(function (found, word) {
        var these = matching(word, shards[word.charAt(0)]);
        if (found === null) return these;
        var both = {};
        Object.keys(found).forEach(function (n) { if (these[n]) both[n] = true; });
        return both;
      }, null);
    }

    form.addEventListener("submit", function (event) { event.preventDefault(); });

    function apply() {
      var hits = indexed(text && text.value);
      if (hits === undefined) {
        // Rows stay as they are until the index files arrive; apply runs again then.
        if (count) count.textContent = "Searching…";
        return;
      }
      var terms = (text && text.value || "").toLowerCase().split(/\s+/).filter(Boolean);
      var shown = 0;

      rows.forEach(function (row) {
        var match;
        if (hits) {
          match = hits[row.dataset.i] === true;
        } else {
          var haystack = row.dataset.search || row.textContent.toLowerCase();
          match = terms.every(function (term) { return haystack.indexOf(term) !== -1; });
        }

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
        count.textContent = shown === 0
          ? "No " + noun + " match. Try fewer or shorter search words, or " + resetLabel.replace(" filters", " the filters") + "."
          : shown === total
          ? "Showing all " + total.toLocaleString("en-GB") + " " + noun + "."
          : "Showing " + shown.toLocaleString("en-GB") + " of " + total.toLocaleString("en-GB") + " " + noun + ".";
      }
      // An empty table is only a row of headings, so it goes while nothing matches.
      wrapper.hidden = shown === 0;

      if (text) setParam("q", text.value.trim());
      selects.forEach(function (select) { setParam(select.dataset.key, select.value); });
      flags.forEach(function (flag) { setParam(flag.dataset.key, flagParam(flag)); });
    }

    // A flag marked `data-default="on"` starts ticked. The URL records only a
    // departure from that — `active=all` once it is unticked — so the default
    // view keeps a clean URL and a link to the full list still gives the full list.
    function flagParam(flag) {
      if (flag.dataset.default === "on") return flag.checked ? "" : "all";
      return flag.checked ? flag.value : "";
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

    if (reset) {
      reset.addEventListener("click", function () {
        if (text) text.value = "";
        selects.forEach(function (select) { select.value = ""; });
        // Back to the view the page opens on, so a default-on flag is ticked again.
        flags.forEach(function (flag) { flag.checked = flag.dataset.default === "on"; });
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
    // Ticked here rather than in the HTML: with JavaScript off every row shows,
    // so a box ticked in the markup would claim a filter that isn't applied.
    flags.forEach(function (flag) {
      var wanted = params.get(flag.dataset.key);
      flag.checked = wanted === flag.value || (flag.dataset.default === "on" && wanted === null);
    });
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
