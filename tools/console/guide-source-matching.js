// Pure, DOM-free helpers for deciding whether a normal-waterline guide's
// saved source matches the media currently on screen in
// form-waterline-guide.html. Kept dependency-free and separate from that
// page's inline script so this logic can be exercised by a plain Node test
// (see tests/console/test_guide_source_matching.mjs) without a browser or
// DOM shim -- this project has no other JS test harness.
//
// A guide's source is either a video (video_id + video_time_seconds) or a
// saved image-sequence still (image_sequence_id + image_filename) -- see
// NormalWaterlineGuide in src/openfloodai/config/site_config.py. Two guides
// (or a guide and the currently displayed media) share a source only when:
//   - both are video-sourced with the same video_id (video_time_seconds is
//     deliberately NOT part of this: different guides may legitimately be
//     traced at different moments of the SAME video), or
//   - both are image-sourced with the same image_sequence_id AND the same
//     image_filename (unlike a video, one image file IS the whole source --
//     two different filenames in the same sequence are two different
//     baselines, never interchangeable).

function guideSourceIdentity(source) {
  if (!source) return null;
  if (source.image_sequence_id) {
    return `image:${source.image_sequence_id}:${source.image_filename || ""}`;
  }
  if (source.video_id) {
    return `video:${source.video_id}`;
  }
  return null;
}

function sourcesMatch(a, b) {
  const identityA = guideSourceIdentity(a);
  const identityB = guideSourceIdentity(b);
  return identityA !== null && identityA === identityB;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { guideSourceIdentity, sourcesMatch };
}
