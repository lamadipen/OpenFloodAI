# Download River Images And Video

Use this page to download public USGS HIVIS images and latest time-lapse videos for local
research, or to save a short clip from any other HTTPS live camera stream you point it at.
It does not upload local files or run validation.

## Use The Home UI

1. Start the existing server with `python3 scripts/run_openfloodai_home_ui.py`, or
   open the desktop app. Restart the server after updating its Python code.
2. Open Home and select **Download River Images and Video**. The page is also available at
   `http://127.0.0.1:8765/river-images.html` with the default server settings.
3. Paste a USGS HIVIS camera page URL. The default is Colorado River near Cameo.
4. Choose a date and whole hour **at the camera**, not at your computer.
5. Enter the camera's IANA timezone if needed, such as `America/Denver`.
6. Select **Download images** and keep the page open while the spinner runs.
7. Read the results for all four time windows. Select an image to open it at full
   size. The page also shows the saved folder. Select **Back to Home** to return.

The page only contacts USGS after submission. Public archives may have missing
images or be temporarily unavailable. Failed slots show a reason; other slots
can still succeed. Retry by submitting again; each submission creates a new folder.

## Download The Latest Video

Enter the camera URL, then select **Download latest time-lapse video**. No date,
hour, timezone, or metadata API key is needed for this action. Keep the page open
while its spinner runs. When complete, play the saved video on the page or use
**Save video** to save another copy through your browser. The page shows the local
folder and download time.

USGS provides a latest MP4 assembled from recent images, not a historical video
for the date/hour selected in the image form. The exact capture range is unknown;
the download time and HTTP Last-Modified value are not camera capture timestamps.
Time-lapse playback seconds do not equal real elapsed seconds. Do not use them to
infer real-time rise speed without source capture times.

The video goes into its own batch folder under `data/river-images/`, with a
`download.json` record marked `latest_timelapse`. Each download creates a new
folder so an earlier copy is not overwritten. An unavailable video shows a clear
message. Transfers are limited to 128 MB and roughly two minutes (plus any pending
socket timeout); incomplete files are removed. The file is checked for an MP4
header, but playback still depends on the codec and whether the source is intact.

This action does not add the MP4 to a site or run validation. To review it later,
use the existing site video intake flow and remember that it is time-lapse footage.
See the [USGS time-lapse API documentation](https://api.waterdata.usgs.gov/docs/nims/#additional-image-products).

## Make A Test Video From Images

After an image download, select **Make test video from these images**. At least
two successfully downloaded images are required. This step reads only local files
and makes no network requests. It orders images by capture time and holds each
for five seconds at 10 frames per second. Four images make a 20-second MP4.
Repeated frames are not new observations, and no motion is invented between images.

The result appears with playback, a **Save video** link, and its local folder.
Browser support for the MPEG-4 codec varies; use a local video player if necessary.
The converter uses the existing OpenCV dependency, with no FFmpeg command-line
installation required. It reports an unavailable encoder instead of saving a
successful result. Inputs must have matching dimensions; one bottom/right pixel
may be cropped to make dimensions even. No extra timestamp or text overlays are
added to the pixels because those could affect change measurements.

Each conversion creates a new batch containing `images_test_timelapse.mp4` and
`download.json`, marked `image_test_timelapse`. The metadata records the source
batch, source image hashes and capture times, playback windows, and skipped slots.
Missing or failed slots are skipped, never replaced with fabricated images. The
source images remain unchanged. Removing source files before conversion produces
an error; it does not silently reduce the video to fewer observations.

To test the workflow, return Home, use your site's **Add Video** action, and select
the generated MP4. Add a human label if you want a comparison. Label windows use
the generated video's playback seconds, not the original observation time. Keep
the generated batch and its metadata: site intake copies the video but does not
import this capture-time map into the validation schema.

For example, images captured at 09:00 and 09:15 appear at playback seconds 0–5 and
5–10. The real gap is 15 minutes, not five seconds. This video can exercise intake,
decoding, sampling, labels, and reports. It is not continuous camera footage and
must not be used to claim detection delay, water speed, or flood accuracy. Results
depend on sampling settings and may miss a brief displayed image. A frozen-image
slideshow is not evidence that the real river stayed unchanged between captures.

## Save A Clip From A Live Camera Stream

This tool works with any HTTPS live stream, not only the USGS archive above — paste
its `.m3u8` (HLS) URL into **Live stream URL**. A live feed can be unreliable: an
attempt either saves a complete clip or fails cleanly with no batch left behind;
it never saves a partial or corrupted file.

Select **Download live camera clip now** for one manual attempt. Set **Clip
length** (2–30 seconds) first; the attempt tries to open the stream and, once
open, captures that many seconds' worth of frames at the stream's own frame
rate before saving. If the stream cannot be opened right now, the status
message says so and nothing is saved — try again later.

To keep trying automatically, turn on **Enable scheduled downloads**, set an
interval (5–1440 minutes), and select **Save schedule**. The schedule is
saved on the server and a single background check runs for as long as the
Home UI server process stays running (not tied to this browser tab): on each
interval, it makes exactly one attempt and records whether it succeeded,
never retrying early after a failure. The status line shows the last attempt's
time and result. Restarting the server keeps the saved schedule but starts a
fresh background check.

Each clip is saved as its own batch under `data/river-images/`, alongside the
USGS downloads, with a `download.json` marked `live_camera_clip`. This
feature does not know anything about the stream's real-world capture time
beyond when the attempt ran; treat clip timing the same way as the latest
USGS time-lapse video above.

## Time And Image Selection

For 09:00, the tool searches four windows: 09:00–09:15, 09:15–09:30,
09:30–09:45 and 09:45–10:00. Each window includes its start and excludes its end.
It selects the first archived image in that window. For example, an image captured
at 09:00:06 is valid for the first window and keeps that actual capture time.
It never substitutes an image from a later window or date.

Source filenames and `download.json` preserve the actual capture timestamp in UTC.
The page shows both requested and actual UTC times. A missing image is not evidence
that the river was unchanged or the camera was offline.

An explicit timezone overrides automatic discovery. Cameo falls back to
`America/Denver`. For other cameras, enter a timezone or configure the server's
`USGS_NIMS_API_KEY` environment variable using your own authorised metadata API key.
No key is included in source code or sent to the browser. Image downloads with an
explicit timezone use the public archive without this metadata key.

Ambiguous or nonexistent daylight-saving hours are rejected. For a repeated hour,
choose the intended UTC hour and use timezone `UTC`. Windows installations include
the `tzdata` package for timezone definitions; macOS/Linux use system timezone data.

## Local Files And Privacy

With the default setup, files go to `data/river-images/<batch-id>/`. When a custom
`--sites-dir` is used, `river-images` is created beside that sites directory.
Desktop builds use the same layout beside their application-data sites folder.
Each image batch contains up to four JPEGs plus `download.json` with source URLs,
requested times, actual capture times, timezone, and per-image outcomes.

Downloads stay separate from validation sites, manifests, labels, exports and
validation runs. They are not automatically approved as training data. The normal
repository `data/*` ignore rule excludes these downloads; keep media local and
check permission before sharing. Delete batch folders manually when no longer
needed. Home's **Delete All Sites** does not delete these separate downloads.

Only official HIVIS camera URLs are accepted for the USGS image/latest-video
actions. Archive requests have timeouts and size limits, redirects are refused,
and the viewer serves only saved batch media. The browser cannot choose an
arbitrary server output folder. The live-camera clip action accepts any HTTPS
URL you provide, but refuses one that resolves to a local or private network
address, so it cannot be used to probe your own network from the browser.

## Command Line

After installing the project, the same downloader is available without the UI:

```bash
python3 scripts/download_river_image.py "2026-09-06 09" --timezone America/Denver
```

Use `--camera-url` for another camera and `-o` for a different local output root.
The downloader creates a unique batch subfolder inside that root and prints JSON
results. A partial or failed batch exits with status 1; four saved images exit 0.

## Code Location

The supplied standalone downloader is integrated as reusable acquisition logic in
`src/openfloodai/ingestion/river_images.py`. The CLI is a thin wrapper. The existing
Home UI server handles routes and `tools/openfloodai-river-images.html` owns the
new form and gallery. Home links to it through `tools/openfloodai-home-ui.html`.
Wheel and desktop packaging include both pages.

The live-camera clip capture lives in `src/openfloodai/ingestion/live_camera.py`,
which runs the actual frame grab in a separate subprocess
(`live_camera_worker.py`) so a stream that never responds can be killed from
outside instead of hanging the server. The background schedule is
`src/openfloodai/ingestion/live_camera_schedule.py`, started once per server
process by the same launchers that start the Home UI server.

Archive selection uses the source script's USGS bucket naming convention and
[S3 listing behaviour](https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjectsV2.html).
Upstream naming or API changes may require an adapter update. These images are
review material, not proof of flood danger or authorisation to issue warnings.
