/* Presentation only. Never merges source records or changes citation IDs. */
(function (root) {
  "use strict";
  function group(segments) {
    const groups = [];
    let current = [], size = 0;
    const flush = () => { if (current.length) groups.push(current); current = []; size = 0; };
    for (const row of segments) {
      const previous = current[current.length - 1];
      const duration = previous && Number.isFinite(row.start) && Number.isFinite(current[0].start) ? row.start-current[0].start : 0;
      const pause = previous && Number.isFinite(previous.end) && Number.isFinite(row.start) ? row.start-previous.end : 0;
      if (previous && (row.asr_issue || previous.asr_issue || row.speaker !== previous.speaker || pause > 4 || size >= 550 || duration >= 120 || (size >= 240 && /[。！？.!?][”’"']?$/.test(previous.text.trim())))) flush();
      current.push(row); size += row.text.length;
      if (row.asr_issue) flush();
    }
    flush();
    return groups;
  }
  function separator(before, after) {
    return !/\s$/.test(before) && /[A-Za-zÀ-ỹ0-9][.!?,;:)\]”’"'»…\s]*$/.test(before) && /^[\[(“‘"'«]*[A-Za-zÀ-ỹ0-9]/.test(after) ? " " : "";
  }
  const api = { group, separator };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.LectureParagraphs = api;
})(typeof window === "undefined" ? {} : window);
