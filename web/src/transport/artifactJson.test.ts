import { describe, expect, it } from "vitest";

import {
  ArtifactHttpStatusError,
  artifactFailureDetail,
  readArtifactJson,
} from "./artifactJson";

describe("artifactFailureDetail", () => {
  it("names the HTTP status instead of implying the feature is absent", () => {
    expect(artifactFailureDetail(new ArtifactHttpStatusError(500))).toBe(
      "产物请求失败（HTTP 500），已停止展示。",
    );
  });

  it("separates a malformed body from an unreachable engine", () => {
    expect(artifactFailureDetail(new SyntaxError("Unexpected token <"))).toBe(
      "产物响应不是有效的 JSON，已停止展示。",
    );
    expect(artifactFailureDetail(new TypeError("Failed to fetch"))).toBe(
      "本地引擎不可达。",
    );
  });
});

describe("readArtifactJson", () => {
  it("passes a 2xx body through", async () => {
    const response = new Response('{"status": "measured"}', { status: 200 });
    await expect(readArtifactJson(response)).resolves.toEqual({
      status: "measured",
    });
  });

  it("throws the status for a non-2xx response", async () => {
    const response = new Response("nope", { status: 503 });
    await expect(readArtifactJson(response)).rejects.toThrow(
      ArtifactHttpStatusError,
    );
  });
});
