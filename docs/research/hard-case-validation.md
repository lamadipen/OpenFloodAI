# Hard-Case Validation Examples

This page lists confusing cases OpenFloodAI should handle carefully.

Simple meaning: these are the situations where the system should say "I cannot safely judge this" instead of acting confident.

These examples are for validation and review only. They do not prove flood detection accuracy, send alerts, upload files, or create public warnings.

The matching machine-readable fixture is:

```text
data/sites/example-site/expected-behavior/hard-cases.jsonl
```

## Expected Behavior

| Case | Input Quality | Validation Result | Simple Reason |
| --- | --- | --- | --- |
| Missing video | `UNKNOWN` | `cannot_compare` | There is no video to process. |
| Empty video | `UNKNOWN` | `cannot_compare` | There are no usable frames. |
| Unreadable video | `UNKNOWN` | `cannot_compare` | The file cannot be read as video. |
| Camera offline | `UNKNOWN` | `cannot_compare` | The camera-style input is unavailable. |
| Heavy glare | `DEGRADED` | `cannot_compare` | Bright glare can hide the watched water area. |
| Rain or noisy image | `DEGRADED` | `cannot_compare` | Rain or noise may look like water movement. |
| Night or dark frame | `DEGRADED` | `cannot_compare` | The watched area is too dark to judge safely. |
| Camera shake | `DEGRADED` | `cannot_compare` | The image may move because the camera moved. |
| Blocked view | `DEGRADED` | `cannot_compare` | Something blocks the watched area. |
| Compression artifacts | `DEGRADED` | `cannot_compare` | Video artifacts can create fake pixel changes. |

## Plain Example

```text
Case: glare-001
Input quality: DEGRADED
Validation result: cannot_compare
Reason: Bright glare makes the watched water area unclear.
```

This does not mean the river is safe. It means the system does not have clear enough evidence.

## Review Rule

Hard cases should stay visible in reports.

- `cannot_compare` is not success.
- `UNKNOWN` is not normal.
- `DEGRADED` means the evidence may be weak or confusing.
- A person should review the video or fix the camera/input before using the result.

Simple example: if the camera is shaking, many pixels may change. That does not prove the water changed. The report should explain the uncertainty.
