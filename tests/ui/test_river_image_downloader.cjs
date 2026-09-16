const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

for (const fails of [false, true]) {
  test(`river image form clears busy state after ${fails ? "failure" : "partial success"}`, async () => {
    const html = fs.readFileSync(path.join(__dirname, "../../tools/openfloodai-river-images.html"), "utf8");
    function element() {
      return {
        value: "", hidden: false, children: [], textContent: "",
        addEventListener(name, handler) { this[name] = handler; },
        setAttribute(name, value) { this[name] = value; },
        appendChild(child) { this.children.push(child); },
        replaceChildren() { this.children = []; },
      };
    }
    const elements = Object.fromEntries([
      "downloadForm", "downloadButton", "downloadSpinner", "downloadStatus", "results",
      "outputDirectory", "cameraUrl", "localDate", "localTime", "timezone",
      "videoDownloadButton", "videoSpinner", "videoStatus", "videoResult",
      "imageVideoActions", "createVideoButton", "createVideoSpinner", "createVideoStatus", "createdVideoResult",
    ].map(id => [id, element()]));
    elements.cameraUrl.value = "https://apps.usgs.gov/hivis/camera/test";
    elements.localDate.value = "2026-09-06";
    elements.localTime.value = "09:00";
    elements.timezone.value = "UTC";
    let finish;
    let calls = 0;
    const pending = new Promise(resolve => { finish = resolve; });
    const context = vm.createContext({
      document: { getElementById: id => elements[id], createElement: element },
      URLSearchParams,
      fetch: async (url, options) => {
        calls++;
        assert.equal(url, "/api/download-river-images");
        assert.equal(JSON.parse(options.body).local_hour, "2026-09-06 09:00");
        await pending;
        if (fails) throw new Error("Connection lost");
        return { ok: true, json: async () => ({
          message: "Downloaded 0 of 4 images.", output_directory: "/local/batch", timezone: "UTC",
          images: [{ status: "missing", requested_utc: "2026-09-06T09:00:00Z", message: "No image" }],
        }) };
      },
    });
    vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
    assert.equal(calls, 0);
    const event = { preventDefault() {} };
    const run = elements.downloadForm.submit(event);
    assert.equal(elements.downloadButton.disabled, true);
    assert.equal(elements.downloadSpinner.hidden, false);
    await elements.downloadForm.submit(event);
    assert.equal(calls, 1);
    finish();
    await run;
    assert.equal(elements.downloadButton.disabled, false);
    assert.equal(elements.downloadSpinner.hidden, true);
    assert.equal(elements.results["aria-busy"], "false");
    assert.match(elements.downloadStatus.textContent, fails ? /Connection lost/ : /0 of 4/);
    if (!fails) assert.equal(elements.results.children.length, 1);
  });
}

for (const fails of [false, true]) {
  test(`latest video ignores image date fields and clears spinner on ${fails ? "error" : "success"}`, async () => {
    const html = fs.readFileSync(path.join(__dirname, "../../tools/openfloodai-river-images.html"), "utf8");
    function element() {
      return {
        value: "", children: [], textContent: "",
        reportValidity() { return true; },
        addEventListener(name, handler) { this[name] = handler; },
        setAttribute(name, value) { this[name] = value; },
        appendChild(child) { this.children.push(child); },
        replaceChildren() { this.children = []; },
      };
    }
    const elements = new Map();
    const get = id => {
      if (!elements.has(id)) elements.set(id, element());
      return elements.get(id);
    };
    get("cameraUrl").value = "https://apps.usgs.gov/hivis/camera/test";
    let finish;
    let calls = 0;
    const pending = new Promise(resolve => { finish = resolve; });
    const context = vm.createContext({
      document: {getElementById: get, createElement: element}, URLSearchParams,
      fetch: async (url, options) => {
        calls++;
        assert.equal(url, "/api/download-river-timelapse");
        assert.deepEqual(JSON.parse(options.body), {camera_url: get("cameraUrl").value});
        await pending;
        return {ok: !fails, json: async () => fails ? {message: "No latest time-lapse available"} : {
          message: "Latest video saved", output_directory: "/local/batch", batch_id: "abc",
          filename: "test_720.mp4", downloaded_at_utc: "2026-09-15T12:00:00Z",
        }};
      },
    });
    vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
    const run = get("videoDownloadButton").click();
    assert.equal(get("videoSpinner").hidden, false);
    assert.equal(get("videoDownloadButton").disabled, true);
    await get("videoDownloadButton").click();
    assert.equal(calls, 1);
    finish();
    await run;
    assert.equal(get("videoSpinner").hidden, true);
    assert.equal(get("videoDownloadButton").disabled, false);
    assert.equal(get("videoResult")["aria-busy"], "false");
    assert.match(get("videoStatus").textContent, fails ? /No latest time-lapse/ : /saved/);
    if (!fails) {
      const link = get("videoResult").children.find(child => child.textContent === "Save video");
      assert.match(link.href, /download=1$/);
      assert.equal(link.download, "test_720.mp4");
    }
  });
}

for (const fails of [false, true]) {
  test(`image-to-video uses the displayed batch and resets controls on ${fails ? "failure" : "success"}`, async () => {
    const html = fs.readFileSync(path.join(__dirname, "../../tools/openfloodai-river-images.html"), "utf8");
    function element() {
      return {
        value: "", children: [], textContent: "",
        addEventListener(name, handler) { this[name] = handler; },
        setAttribute(name, value) { this[name] = value; },
        appendChild(child) { this.children.push(child); },
        replaceChildren() { this.children = []; },
      };
    }
    const elements = new Map();
    const get = id => {
      if (!elements.has(id)) elements.set(id, element());
      return elements.get(id);
    };
    let finish;
    let calls = 0;
    const pending = new Promise(resolve => { finish = resolve; });
    const context = vm.createContext({
      document: {getElementById: get, createElement: element}, URLSearchParams,
      fetch: async (url, options) => {
        calls++;
        assert.equal(url, "/api/create-river-test-video");
        assert.deepEqual(JSON.parse(options.body), {batch_id: "source-batch"});
        await pending;
        return {ok: !fails, json: async () => fails ? {message: "Encoder unavailable"} : {
          message: "Test video created", batch_id: "video-batch", filename: "images_test_timelapse.mp4",
          output_directory: "/local/video", source_image_count: 2, duration_seconds: 10,
          frames: [{captured_utc: "2026-09-06T09:00:00Z", playback_time_window_seconds: [0, 5]}],
          skipped_slots: [{status: "missing"}],
        }};
      },
    });
    vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
    context.renderResults({batch_id: "single", images: [{status: "downloaded", filename: "a.jpg"}]});
    assert.equal(get("createVideoButton").disabled, true);
    await get("createVideoButton").click();
    assert.equal(calls, 0);
    context.renderResults({batch_id: "source-batch", images: [
      {status: "downloaded", filename: "a.jpg"}, {status: "downloaded", filename: "b.jpg"},
    ]});
    assert.equal(get("createVideoButton").disabled, false);
    const run = get("createVideoButton").click();
    assert.equal(get("createVideoSpinner").hidden, false);
    assert.equal(get("downloadButton").disabled, true);
    await get("createVideoButton").click();
    assert.equal(calls, 1);
    finish();
    await run;
    assert.equal(get("createVideoSpinner").hidden, true);
    assert.equal(get("createVideoButton").disabled, false);
    assert.equal(get("downloadButton").disabled, false);
    assert.equal(get("createdVideoResult")["aria-busy"], "false");
    assert.match(get("createVideoStatus").textContent, fails ? /Encoder unavailable/ : /created/);
    if (!fails) {
      assert.ok(get("createdVideoResult").children.some(child => /gaps/.test(child.textContent)));
      const link = get("createdVideoResult").children.find(child => child.textContent === "Save video");
      assert.equal(link.download, "images_test_timelapse.mp4");
    }
  });
}
