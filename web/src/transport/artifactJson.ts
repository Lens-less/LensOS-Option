// Shared failure vocabulary for capture-bound artifact fetches (signal /
// series). A non-2xx response, a malformed body, and an unreachable engine
// are three different operational facts; folding them into one message hides
// the difference from whoever is debugging the pipeline.
import { ReportLoadError, requestJson } from "./requestJson";

export async function loadArtifactJson(url: string, signal: AbortSignal): Promise<unknown> {
  const { payload } = await requestJson(url, { init: { signal } });
  return payload;
}

export class ArtifactHttpStatusError extends Error {
  constructor(readonly status: number) {
    super(`HTTP ${status}`);
  }
}

/** Throws {@link ArtifactHttpStatusError} for non-2xx artifact responses. */
export async function readArtifactJson(response: Response): Promise<unknown> {
  if (!response.ok) {
    throw new ArtifactHttpStatusError(response.status);
  }
  return response.json();
}

export function artifactFailureDetail(error: unknown): string {
  if (error instanceof ReportLoadError && error.kind === "timeout") {
    return "读取产物超时，已停止展示；请刷新后重试。";
  }
  if (error instanceof ArtifactHttpStatusError ||
      (error instanceof ReportLoadError && error.kind === "http")) {
    return `产物请求失败（HTTP ${error.status}），已停止展示。`;
  }
  if (error instanceof SyntaxError ||
      (error instanceof ReportLoadError && error.kind === "invalid")) {
    return "产物响应不是有效的 JSON，已停止展示。";
  }
  return "本地引擎不可达。";
}
