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

  // Whether every search term matches a word of `text`, by the same rules as
  // the word index: whole words under four letters, word starts otherwise.
  function matchesAll(terms, text) {
    var words = searchWords(text);
    return terms.every(function (term) {
      return words.some(function (word) {
        return term.length < 4 ? word === term : word.lastIndexOf(term, 0) === 0;
      });
    });
  }

  // Organisations and datasets whose names match a search, shown above the
  // agreements it found (pipeline/search.py, `names`). Each entry is
  // [name, slug, agreements, other names, controller of, last listed]; a match
  // on another name says which.
  function nameMatches(box, names, value) {
    var terms = searchWords(value);
    while (box.firstChild) box.removeChild(box.firstChild);
    var any = false;
    [["organisations", "Organisations"], ["datasets", "Datasets"]].forEach(function (kind) {
      if (!terms.length) return;
      var found = [];
      names[kind[0]].forEach(function (entry) {
        if (matchesAll(terms, entry[0])) found.push([entry, null]);
        else {
          var other = entry[3].filter(function (name) { return matchesAll(terms, name); })[0];
          if (other) found.push([entry, other]);
        }
      });
      if (!found.length) return;
      any = true;
      var line = document.createElement("p");
      var label = document.createElement("strong");
      label.textContent = kind[1] + ": ";
      line.appendChild(label);
      found.slice(0, 5).forEach(function (match, i) {
        var entry = match[0];
        if (i) line.appendChild(document.createTextNode("; "));
        var link = document.createElement("a");
        link.href = box.dataset.base + "/" + kind[0] + "/" + entry[1] + "/";
        link.textContent = entry[0];
        line.appendChild(link);
        var notes = [];
        if (match[1]) notes.push("recorded as " + match[1]);
        if (entry[5]) notes.push("no longer in the register, last listed " + entry[5]);
        else if (entry[2]) notes.push(entry[2].toLocaleString("en-GB") + (entry[2] === 1 ? " agreement" : " agreements"));
        else if (entry[4]) notes.push("data controller on " + entry[4].toLocaleString("en-GB") + (entry[4] === 1 ? " agreement" : " agreements"));
        if (notes.length) line.appendChild(document.createTextNode(" (" + notes.join(", ") + ")"));
      });
      if (found.length > 5) {
        line.appendChild(document.createTextNode("; "));
        var more = document.createElement("a");
        more.href = box.dataset.base + "/" + kind[0] + "/?q=" + encodeURIComponent(value.trim());
        more.textContent = "and " + (found.length - 5) + " more";
        line.appendChild(more);
      }
      box.appendChild(line);
    });
    box.hidden = !any;
  }

  document.querySelectorAll("[data-filter-form]").forEach(function (form) {
    // One form can filter several tables: the changes page searches all of its
    // tables at once. `data-target` lists their ids.
    var tables = form.dataset.target.split(/\s+/)
      .map(function (id) { return document.getElementById(id); })
      .filter(Boolean);
    if (!tables.length) return;

    var rows = [];
    tables.forEach(function (table) {
      Array.prototype.forEach.call(table.tBodies[0].rows, function (row) { rows.push(row); });
    });
    var count = form.parentNode.querySelector("[data-filter-count]");
    var text = form.querySelector("[data-filter-text]");
    var selects = Array.prototype.slice.call(form.querySelectorAll("[data-filter-select]"));
    var flags = Array.prototype.slice.call(form.querySelectorAll("[data-filter-flag]"));
    var noun = (count && /\b(agreements|organisations|datasets|changes)\b/.exec(count.textContent) || [, "rows"])[1];
    var reset = form.querySelector("[data-filter-reset]");
    // "Clear filters", or "Reset filters" where a filter is on by default. A
    // form with only a search box has no button: the box clears itself.
    var resetLabel = reset ? reset.textContent.trim().toLowerCase() : "";
    var total = rows.length;
    var timer;

    // Filters beyond the search box, folded behind a button on a phone (the
    // stylesheet shows the button, and lets the fold take effect, only there).
    // The button says how many are on, so a folded filter is never a hidden one.
    var more = form.querySelector("[data-filter-more]");
    var toggle = null;
    if (more) {
      toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "filter-toggle";
      toggle.setAttribute("aria-controls", more.id);
      more.parentNode.insertBefore(toggle, more);
      more.classList.add("is-folded");
      toggle.addEventListener("click", function () {
        more.classList.toggle("is-folded");
        labelToggle();
      });
      labelToggle();
    }
    function labelToggle() {
      if (!toggle) return;
      var folded = more.classList.contains("is-folded");
      var on = selects.filter(function (select) { return select.value; }).length +
        flags.filter(function (flag) { return flag.checked; }).length;
      toggle.textContent = (folded ? "Show filters" : "Hide filters") + (on ? " (" + on + " on)" : "");
      toggle.setAttribute("aria-expanded", folded ? "false" : "true");
    }
    // Where this table's word index is, if it has one. Files are fetched when a
    // search needs them and kept; until they arrive, or if they can't be had,
    // the search falls back to the text each row carries in `data-search`, or
    // to the text it shows where it carries none.
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

    // Agreements no longer in the register, listed apart below the table. A
    // search looks through them too, with a count of their own, so the main
    // count still means agreements in the register. Only the search applies:
    // the other filters describe agreements in the register.
    var archivedTable = document.getElementById("archived-table");
    var archivedCount = document.querySelector("[data-archived-count]");
    function filterArchived(value) {
      if (!archivedTable || !text) return;
      var terms = searchWords(value);
      var archivedRows = Array.prototype.slice.call(archivedTable.tBodies[0].rows);
      var shown = 0;
      archivedRows.forEach(function (row) {
        var match = !terms.length || matchesAll(terms, row.dataset.search || row.textContent);
        row.hidden = !match;
        if (match) shown++;
      });
      (archivedTable.closest(".table-scroll") || archivedTable).hidden = shown === 0;
      if (archivedCount) {
        archivedCount.hidden = !terms.length;
        var total = archivedRows.length;
        archivedCount.textContent = shown === 0
          ? "None of these " + total.toLocaleString("en-GB") + " matches the search."
          : shown + " of " + total.toLocaleString("en-GB") + " match the search.";
      }
    }

    // Where a search here also looks up organisation and dataset names. The
    // file is fetched once, when the first search needs it.
    var namesBox = form.parentNode.querySelector("[data-name-matches]");
    var names, namesLoading;
    function showNames() {
      if (!namesBox || !window.fetch) return;
      var value = text ? text.value : "";
      if (names) return nameMatches(namesBox, names, value);
      if (!value.trim()) { namesBox.hidden = true; return; }
      if (!namesLoading) {
        namesLoading = fetch(namesBox.dataset.names)
          .then(function (response) { if (!response.ok) throw new Error(response.status); return response.json(); })
          .then(function (data) { names = data; showNames(); })
          .catch(function () { /* The agreements still filter; only the names are missing. */ });
      }
    }

    function apply() {
      var hits = indexed(text && text.value);
      if (hits === undefined) {
        // Rows stay as they are until the index files arrive; apply runs again then.
        if (count) count.textContent = "Searching…";
        return;
      }
      var terms = (text && text.value || "").toLowerCase().split(/\s+/).filter(Boolean);
      var shown = 0;
      // An agreement opened from a search shows where the words are: its page
      // reads `q` and highlights them (assets/highlight.js).
      var carried = indexUrl && text && text.value.trim() ? "?q=" + encodeURIComponent(text.value.trim()) : "";

      rows.forEach(function (row) {
        var match;
        // A row with no number (an agreement no longer listed) isn't indexed,
        // so it is searched by the text it carries.
        if (hits && row.dataset.i) {
          match = hits[row.dataset.i] === true;
        } else {
          var haystack = row.dataset.search || row.textContent.toLowerCase();
          match = terms.every(function (term) { return haystack.indexOf(term) !== -1; });
        }

        if (match) {
          match = selects.every(function (select) {
            if (!select.value) return true;
            var value = row.dataset[select.dataset.key] || "";
            // A row can carry several values, space-separated, where one
            // agreement fits more than one option (`data-filter-tokens`).
            if (select.hasAttribute("data-filter-tokens")) {
              return value.split(" ").indexOf(select.value) !== -1;
            }
            return value === select.value;
          });
        }
        if (match) {
          match = flags.every(function (flag) {
            return !flag.checked || row.dataset[flag.dataset.key] === flag.value;
          });
        }

        if (indexUrl) {
          var link = row.querySelector("th a");
          if (link) {
            if (link.dataset.href === undefined) link.dataset.href = link.getAttribute("href");
            link.setAttribute("href", link.dataset.href + carried);
          }
        }

        row.hidden = !match;
        if (match) shown++;
      });

      if (count) {
        count.textContent = shown === 0
          ? "No " + noun + " match. Try fewer or shorter search words" + (resetLabel ? ", or " + resetLabel.replace(" filters", " the filters") : "") + "."
          : shown === total
          ? "Showing all " + total.toLocaleString("en-GB") + " " + noun + "."
          : "Showing " + shown.toLocaleString("en-GB") + " of " + total.toLocaleString("en-GB") + " " + noun + ".";
      }
      // An empty table is only a row of headings, so it goes while nothing
      // matches. A table folded away that a search finds rows in is unfolded.
      tables.forEach(function (table) {
        var visible = Array.prototype.some.call(table.tBodies[0].rows, function (row) { return !row.hidden; });
        (table.closest(".table-scroll") || table).hidden = !visible;
        var folded = table.closest("details");
        if (folded && visible && terms.length) folded.open = true;
      });

      labelToggle();
      showNames();
      filterArchived(text ? text.value : "");
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
