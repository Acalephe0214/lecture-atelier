/* Pure transport rules, shared with the dependency-free Node tests. */
(function (root) {
  "use strict";
  function segmentAt(segments, time) {
    if (!Number.isFinite(time)) return null;
    let candidate = null;
    for (const segment of segments) {
      if (segment.start === null || segment.start === undefined) continue;
      if (time < segment.start) break;
      candidate = segment;
    }
    if (candidate && candidate.end !== null && candidate.end !== undefined && time >= candidate.end) return null;
    return candidate;
  }
  function actionFor(segmentId, activeId, paused, started) {
    if (!started || segmentId !== activeId) return "play";
    return paused ? "resume" : "pause";
  }
  const api = { segmentAt, actionFor };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.LecturePlayback = api;
})(typeof window === "undefined" ? {} : window);
