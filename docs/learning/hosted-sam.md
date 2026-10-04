# Optional Hosted SAM Segmentation

OpenFloodAI can optionally send images you choose to Meta's hosted SAM 3.1
service. SAM outlines a concept you name, such as `water` or `riverbank`, so a
person can review an image faster. It is **off by default**. Ingestion,
validation, and review all work offline with no key and no SAM.

A SAM outline is an unreviewed machine prediction. It is not a human label, not
a detected waterline, not calibrated accuracy, and not a flood decision. Zero
matches, a failed request, and an unreviewed result never mean safe, normal, or
no water-level change.

## Set up

1. Create an account and arrange billing with Meta:
   [SAM hosted API: signup and pricing](https://dev.meta.ai/models/sam-3-1).
   You pay Meta through your own account. OpenFloodAI does not bill you.
2. Open **Settings** in the console and turn on **Hosted SAM segmentation**.
3. Paste your API key and select **Save key**. The key field is masked. Only the
   last four characters are shown afterward. Use **Replace key** or **Remove
   key** to change it.
4. Install Meta's SAM parser, which reads replies and decodes masks. It is
   an optional extra, because it is distributed under Meta's own SAM License
   rather than this project's MIT license:
   `pip install "openfloodai[sam]"` (or `pip install meta_sam_parser`). Without
   it, the Start button stays unavailable and nothing is sent.
5. Optional, for a local operator: set the `OPENFLOODAI_SAM_API_KEY`
   environment variable instead. A key saved in Settings wins over it.

## Run segmentation

1. Open a run in **Review** and select an image.
2. In **Hosted SAM segmentation**, choose `water`, `riverbank`, or both. Each
   concept is its own paid request. The panel shows the exact number of
   requests before you start.
3. The first time, confirm that the selected image, cropped to the watched
   area, will be uploaded to Meta and your account may be charged.
4. Select **Start segmentation**. Nothing is uploaded before this step, and
   reloading the page never starts one.
5. The predicted mask is shown over the original image with the unchanged
   human guide. Mark each result **Accepted**, **Rejected**, or **Needs
   correction**. These marks are saved separately and do not create human
   labels.

Batches are limited to 10 images and 2 concepts. Requests are sent one at a
time, with a 60 second timeout and **no automatic retries**: a request that may
have reached Meta could already be billed, so it is never resent for you. After
an invalid key, no quota, a rate limit, a timeout, or a network failure, the
rest of the batch is not sent.

## How your key is handled

- Requests are made by the local backend. The browser never receives the key
  after you submit it, only a "configured" flag and a masked hint.
- The key is held in the app's memory for the session. It is never written to a
  site folder, manifest, run folder, settings file, log, or browser storage.
  Removing it clears it. Restarting the app clears it and the upload
  confirmation.
- Provider error text is redacted before it is kept or shown.
- **Disabling** the plugin stops new uploads. **Removing the key** clears it
  from the app. Neither reverses charges for requests already sent.

## What is saved

Each run is its own folder under `outputs/hosted-sam-runs/<run_id>/` and is not
edited afterward. A rerun is a new run.

- Image SHA-256 and capture time, provider, requested model, the prompt, and the
  crop used (watched area as percentages, the pixel rectangle, source size, and
  JPEG quality), request status, and processing time.
- Raw full-size masks as PNG files in original-image pixels, kept apart from the
  overlay, which is drawn on request.
- Human review decisions in an append-only `reviews.jsonl`.
- The model Meta returns is not yet read from the reply, so only the requested
  model (`sam-3.1`) is recorded. A confidence is saved only when the service
  sends one, exactly as sent. It is not calibrated accuracy.

An identical request (same image bytes, model, prompt, and crop) reuses the
saved result without a new paid request. Any change to the image, the watched
area, or the prompt makes a new request. Failed attempts are never reused.

## Coordinates

The service accepts text concepts, not boxes or points. OpenFloodAI crops the
image to the site's watched area, sends the crop, then shifts each returned box
and mask by the crop origin (a mask is the size of its box and anchored at the
box's top-left corner) to place it on the original image. A mask that does
not fit inside the crop is rejected rather than clipped, so a mask can never
land outside the watched area or on the wrong image. The crop is a rectangle:
a bank-region outline is not a waterline, and its vegetation-facing edge is not
a detected water boundary.

## Privacy and limits

- Selected images leave your device. The provider page does not state how long
  uploaded images are kept or whether they are used for training. Read Meta's
  [terms](https://www.facebook.com/policies_center/) and
  [privacy policy](https://www.facebook.com/privacy/policy/) before uploading.
  Service terms are separate from the downloadable SAM model license.
- The provider page listed `$2.50/1k images` when this was written. Check the
  current price with Meta.
- Replies are read with Meta's own `meta_sam_parser` package, which defines the
  stream format, the inclusive box corners, and the mask codec. The HTTP status
  codes the service uses for quota and rate limits could not be confirmed
  without a paid key, so any unexpected reply is reported as a malformed
  response or provider error rather than guessed. A reply that ends early, fails,
  is refused, or has an unreadable object is never shown as "no match".
- The meaning of an empty successful reply is also unconfirmed against the live
  service. Only a finished reply with no objects is shown as "no match".
- A small pilot on representative images, authorized separately, should record
  review effort, processing time, and cost before any claim about usefulness.
  One successful image says nothing about accuracy.
