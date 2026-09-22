# Changelog

## v5.0.0 — New validation console

A new, redesigned console for setting up sites, downloading evidence, and reviewing results — built to replace scattered legacy pages with one clearer flow. Existing pages are untouched; this is an additional, separate UI.

### Setting up a site
- **Create a site from a video** — pick a video file when creating a site and its name, folder, and camera ID are filled in for you automatically (still fully editable).
- **See videos already on a site** — the Setup tab now lists every video already added, with its purpose, dataset split, and whether it has a human label — no more guessing what's there.
- **More purpose options when adding a video** — the full set of options (practice, possible rising/falling water, hard case, camera problem, etc.) is available, not just two.
- **Video ID fills in automatically** — pick a video file on the Add Media form and its ID is derived from the filename, still editable.

### Drawing the watched area and riverbank
- **Redraw the watched area from scratch** — click and drag anywhere on the image to draw a brand-new watched area, or use "Clear and redraw" to start over, instead of only being able to nudge the existing box.
- **Works on video-only sites too** — the watched-area and riverbank editors used to require a downloaded image sequence; they now also work directly on a site's video, letting you scrub to a frame and draw on it.
- **Multiple riverbank lines in one visit** — trace as many banks as you need (e.g. left bank and right bank) in a single session; every line stays visible while you draw the next one, and each can be labeled, confirmed, or deleted independently.
- **See the watched area while tracing the riverbank** — the watched area now shows as an outline while you draw riverbank lines, and new points are kept inside it, so you can't accidentally draw outside the area that's actually being analyzed.

### Reviewing results
- **A new page for reviewing video results** — browse every comparison window from a video validation run, see the machine's result and score on a clear chart, watch the exact video clip, and record what you see — all without leaving the page.
- **The watched area and riverbank show up on the video** — a toggle overlays the saved watched area and riverbank lines directly on the video preview, so you can check they still line up with what the camera is showing.
- **Clearer, easier-to-read charts** — the change-score chart now has gridlines, a trend line, and readable axis labels, and results use a consistent color scheme (green = no change, blue = cannot judge, red = possible change) throughout.
- **Always know what's set up and what isn't** — the site overview page now clearly shows whether image-sequence review, video review, or both are ready to use, with a one-click way to run whichever one is missing.

### Dataset tags
- **Tag individual videos, not just image sequences** — assign a video to practice or locked-validation independently of any image sequence on the same site.

### Gage (water-level) data
- **Gage data downloads automatically** — when you download a timestamped image sequence for a recognized river camera, USGS gage readings for the same dates now come down with it, matched to each image's exact timestamp — no separate step required.
- **Optional** — an "Also fetch USGS gage data" checkbox lets you skip this if you only want the images.

### Getting around
- **Clearer navigation from the home page** — the links to the console, review workspace, image downloader, and river camera tracker are now clear buttons with icons, not a cramped line of text.
- **A way back from the new console** — the console now has a link back to the classic home page, so you're never stuck without a way back.

### Behind the scenes
- Several real bugs were found and fixed along the way: watched-area/riverbank points weren't being saved in the right coordinate system, a riverbank save was missing a required field, and video-only sites weren't correctly recognized by several pages.
