const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function element() {
  return {
    value: "", checked: false, hidden: false, children: [], textContent: "",
    reportValidity() { return true; },
    addEventListener(name, handler) { this[name] = handler; },
    setAttribute(name, value) { this[name] = value; },
    appendChild(child) { this.children.push(child); },
    replaceChildren() { this.children = []; },
  };
}

function makeElements() {
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  };
  return get;
}

function scheduleFixture(overrides) {
  return Object.assign({
    enabled: false, stream_url: "https://camera.example.com/stream.m3u8",
    interval_minutes: 60, duration_seconds: 8,
    last_run_utc: null, last_result: null, last_message: null,
  }, overrides);
}

function loadScript(context) {
  const html = fs.readFileSync(path.join(__dirname, "../../tools/openfloodai-river-images.html"), "utf8");
  vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
}

test("live camera form submit never reloads the page (no submit-type button)", async () => {
  const get = makeElements();
  let prevented = false;
  const context = vm.createContext({
    document: { getElementById: get, createElement: element },
    URLSearchParams,
    fetch: async () => ({ ok: true, json: async () => scheduleFixture() }),
  });
  loadScript(context);
  await Promise.resolve();
  get("liveCameraForm").submit({ preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
});

test("page load fetches and renders the saved schedule status", async () => {
  const get = makeElements();
  const context = vm.createContext({
    document: { getElementById: get, createElement: element },
    URLSearchParams,
    fetch: async (url) => {
      assert.equal(url, "/api/live-camera-schedule");
      return {
        ok: true,
        json: async () => scheduleFixture({
          enabled: true, interval_minutes: 45,
          last_run_utc: "2026-09-16T08:00:00+00:00", last_result: "success", last_message: "Saved.",
        }),
      };
    },
  });
  loadScript(context);
  await context.loadLiveCameraSchedule();
  assert.equal(get("liveCameraScheduleEnabled").checked, true);
  assert.equal(get("liveCameraScheduleInterval").value, 45);
  assert.match(get("liveCameraScheduleStatus").textContent, /every 45 minutes/);
  assert.match(get("liveCameraScheduleStatus").textContent, /Succeeded/);
});

for (const fails of [false, true]) {
  test(`manual live camera download clears busy state on ${fails ? "failure" : "success"}`, async () => {
    const get = makeElements();
    get("liveCameraUrl").value = "https://camera.example.com/stream.m3u8";
    get("liveCameraDuration").value = "8";
    let finish;
    let downloadCalls = 0;
    const pending = new Promise(resolve => { finish = resolve; });
    const context = vm.createContext({
      document: { getElementById: get, createElement: element },
      URLSearchParams,
      fetch: async (url, options) => {
        if (url === "/api/live-camera-schedule") return { ok: true, json: async () => scheduleFixture() };
        downloadCalls++;
        assert.equal(url, "/api/download-live-camera-clip");
        assert.deepEqual(JSON.parse(options.body), {
          stream_url: "https://camera.example.com/stream.m3u8", duration_seconds: 8,
        });
        await pending;
        if (fails) {
          return { ok: false, json: async () => ({ message: "Could not open the live camera stream." }) };
        }
        return {
          ok: true,
          json: async () => ({
            message: "Live camera clip saved.", output_directory: "/local/clip-batch",
            batch_id: "abc123", filename: "live_camera_clip.mp4",
          }),
        };
      },
    });
    loadScript(context);
    await Promise.resolve();
    const run = get("liveCameraDownloadButton").click();
    assert.equal(get("liveCameraDownloadButton").disabled, true);
    assert.equal(get("liveCameraSpinner").hidden, false);
    await get("liveCameraDownloadButton").click();
    assert.equal(downloadCalls, 1);
    finish();
    await run;
    assert.equal(get("liveCameraDownloadButton").disabled, false);
    assert.equal(get("liveCameraSpinner").hidden, true);
    assert.equal(get("liveCameraResult")["aria-busy"], "false");
    assert.match(
      get("liveCameraStatus").textContent,
      fails ? /Could not open the live camera stream/ : /clip saved/
    );
    if (!fails) {
      const link = get("liveCameraResult").children.find(child => child.textContent === "Save video");
      assert.equal(link.download, "live_camera_clip.mp4");
    }
  });
}

for (const fails of [false, true]) {
  test(`saving the schedule updates its status on ${fails ? "rejection" : "success"}`, async () => {
    const get = makeElements();
    get("liveCameraUrl").value = "https://camera.example.com/stream.m3u8";
    get("liveCameraDuration").value = "8";
    get("liveCameraScheduleInterval").value = "30";
    get("liveCameraScheduleEnabled").checked = true;
    let saveCalls = 0;
    const context = vm.createContext({
      document: { getElementById: get, createElement: element },
      URLSearchParams,
      fetch: async (url, options) => {
        if (url === "/api/live-camera-schedule") return { ok: true, json: async () => scheduleFixture() };
        saveCalls++;
        assert.equal(url, "/api/set-live-camera-schedule");
        assert.deepEqual(JSON.parse(options.body), {
          enabled: true, stream_url: "https://camera.example.com/stream.m3u8",
          interval_minutes: 30, duration_seconds: 8,
        });
        if (fails) return { ok: false, json: async () => ({ message: "Interval must be between 5 and 1440 minutes." }) };
        return { ok: true, json: async () => scheduleFixture({ enabled: true, interval_minutes: 30 }) };
      },
    });
    loadScript(context);
    await Promise.resolve();
    await get("liveCameraScheduleSaveButton").click();
    assert.equal(saveCalls, 1);
    assert.match(
      get("liveCameraScheduleStatus").textContent,
      fails ? /Interval must be between/ : /every 30 minutes/
    );
  });
}
