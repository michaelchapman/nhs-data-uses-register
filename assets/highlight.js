/* On an agreement page opened from a search (?q=dementia), highlight the words
   searched for, open the purpose sections that contain them and scroll to the
   first. Words match as the search matched them (assets/filter.js): a whole
   word under four letters, the start of a word from four, apostrophes ignored,
   and an acronym also in its plural ("GP" finds "GPs"). Without JavaScript the
   page is simply the page. */

(function () {
  "use strict";

  var query;
  try { query = new URLSearchParams(window.location.search).get("q"); } catch (error) { return; }
  var words = (query || "").toLowerCase().replace(/['’]/g, "").match(/[a-z0-9]+/g);
  if (!words) return;

  function escape(text) { return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
  // Letters of a word, allowing an apostrophe between any two: "kings" finds "King's".
  function spelled(word) { return word.split("").map(escape).join("['’]?"); }

  // A short word matches whole, with an "s" or, if it ends in "s", without it;
  // `qualifies` then keeps only the acronym forms among those extras.
  var pattern = new RegExp(words.map(function (word) {
    if (word.length >= 4) return "\\b" + spelled(word) + "[a-z0-9]*";
    var forms = [spelled(word) + "s?"];
    if (word.length > 1 && word.charAt(word.length - 1) === "s") forms.push(spelled(word.slice(0, -1)));
    return "\\b(?:" + forms.join("|") + ")(?![a-z0-9])";
  }).join("|"), "gi");

  function qualifies(found) {
    var bare = found.replace(/['\u2019]/g, "");
    var lower = bare.toLowerCase();
    // The word searched for, or a longer word it starts.
    if (words.some(function (w) { return lower === w || (w.length >= 4 && lower.lastIndexOf(w, 0) === 0); })) return true;
    // Otherwise an acronym's other form, in capitals: "GP" for "gps", and "GPs"
    // for "gp" with a lower-case s, so not "GPS" or "has" for "ha".
    var stem = words.indexOf(lower + "s") !== -1 ? bare : bare.slice(-1) === "s" ? bare.slice(0, -1) : "";
    return /[A-Z]/.test(stem) && stem === stem.toUpperCase();
  }

  var marks = [];
  document.querySelectorAll("[data-highlight]").forEach(function (scope) {
    var walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
    var nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(function (node) {
      var text = node.nodeValue, last = 0, match, pieces = [];
      pattern.lastIndex = 0;
      while ((match = pattern.exec(text))) {
        if (!qualifies(match[0])) continue;
        pieces.push(document.createTextNode(text.slice(last, match.index)));
        var mark = document.createElement("mark");
        mark.textContent = match[0];
        pieces.push(mark);
        marks.push(mark);
        last = match.index + match[0].length;
      }
      if (!pieces.length) return;
      pieces.push(document.createTextNode(text.slice(last)));
      var fragment = document.createDocumentFragment();
      pieces.forEach(function (piece) { fragment.appendChild(piece); });
      node.parentNode.replaceChild(fragment, node);
    });
  });
  if (!marks.length) return;

  marks.forEach(function (mark) {
    var section = mark.closest("details");
    if (section) section.open = true;
  });

  var note = document.querySelector("[data-search-note]");
  if (note) {
    note.textContent = "Your search, “" + query.trim() + "”, is highlighted " +
      (marks.length === 1 ? "once" : marks.length + " times") + " on this page. ";
    var clear = document.createElement("a");
    clear.href = window.location.pathname;
    clear.textContent = "Remove the highlighting";
    note.appendChild(clear);
    note.hidden = false;
  }
  marks[0].scrollIntoView({ block: "center" });
})();
