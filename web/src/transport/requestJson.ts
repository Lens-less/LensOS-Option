/** Transport-only helpers shared by local and public builds. */
export type ReportLoadErrorKind = "network" | "timeout" | "http" | "invalid" | "aborted" | "unknown";

const ERROR_MESSAGES: Record<ReportLoadErrorKind, string> = {
  network: "Could not connect to the report service",
  timeout: "Report request timed out",
  http: "Report service returned an unsuccessful response",
  invalid: "Report validation failed; the safety boundary remains closed",
  aborted: "Report request was cancelled",
  unknown: "Report could not be loaded",
};

export class ReportLoadError extends Error {
  constructor(readonly kind: ReportLoadErrorKind, readonly status?: number) {
    // This stable, safe tag also survives Chrome's message serialization.
    super(`[report:${kind}] ${ERROR_MESSAGES[kind]}`);
    this.name = "ReportLoadError";
  }
}

export function reportLoadErrorKind(error: unknown): ReportLoadErrorKind {
  if (error instanceof ReportLoadError) return error.kind;
  const message = error instanceof Error ? error.message : "";
  const tag = /^\[report:(network|timeout|http|invalid|aborted|unknown)\]/.exec(message);
  if (tag) return tag[1] as ReportLoadErrorKind;
  if (/failed to fetch|network(?: request)?(?: error)?|connection (?:refused|reset)|fetch failed/i.test(message)) return "network";
  if (/timed out|timeout/i.test(message)) return "timeout";
  if (/safety boundary|report.*(?:invalid|validation|unverifiable)/i.test(message)) return "invalid";
  return "unknown";
}

export function reportLoadErrorCopy(kind: ReportLoadErrorKind): { title: string; action: string } {
  switch (kind) {
    case "network": return { title: "无法连接研究服务", action: "请检查网络连接；使用本地版时，请确认研究引擎已经启动，然后重新读取。" };
    case "timeout": return { title: "读取研究数据超时", action: "研究服务未在限定时间内完成响应。请检查连接或稍后重新读取。" };
    case "http": return { title: "研究服务暂不可用", action: "服务未成功返回报告。请稍后重试；若持续失败，请联系服务维护者。" };
    case "invalid": return { title: "报告校验失败", action: "报告格式或安全约束不符合要求，当前结果已撤下。请更新研究引擎或由发布者重新生成快照后再试。" };
    case "aborted": return { title: "读取已取消", action: "此次读取已取消，可以重新读取研究报告。" };
    default: return { title: "读取未完成", action: "此次读取未能完成，请重新读取；若持续失败，请联系服务维护者。" };
  }
}

export type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
export const REPORT_REQUEST_TIMEOUT_MS = 10_000;

/** A single deadline covers both response headers and JSON body consumption. */
export async function requestJson(url: string, options?: {
  fetchImpl?: FetchLike;
  init?: RequestInit;
  timeoutMs?: number;
}): Promise<{ response: Response; payload: unknown }> {
  const fetchImpl = options?.fetchImpl ?? globalThis.fetch;
  if (typeof fetchImpl !== "function") throw new ReportLoadError("network");
  const { headers: initHeaders, signal: externalSignal, ...init } = options?.init ?? {};
  if (externalSignal?.aborted) throw new ReportLoadError("aborted");
  const headers = new Headers(initHeaders);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  const controller = new AbortController();
  const requestedTimeout = options?.timeoutMs ?? REPORT_REQUEST_TIMEOUT_MS;
  const timeoutMs = Number.isFinite(requestedTimeout) && requestedTimeout > 0
    ? requestedTimeout : REPORT_REQUEST_TIMEOUT_MS;
  let cancel: (kind: "timeout" | "aborted") => void = () => undefined;
  const cancelled = new Promise<never>((_, reject) => {
    cancel = (kind) => {
      reject(new ReportLoadError(kind));
      controller.abort();
    };
  });
  const onAbort = () => cancel("aborted");
  externalSignal?.addEventListener("abort", onAbort, { once: true });
  const timer = globalThis.setTimeout(() => cancel("timeout"), timeoutMs);
  try {
    const request = (async () => {
      let response: Response;
      try {
        response = await fetchImpl(url, {
          ...init, method: "GET", body: undefined, cache: "no-store", headers,
          // Reports and capture-bound artifacts must come from the requested
          // endpoint; following a redirect would silently change provenance.
          redirect: "error",
          signal: controller.signal,
        });
      } catch {
        throw new ReportLoadError("network");
      }
      if (response.redirected) throw new ReportLoadError("invalid");
      if (!response.ok) throw new ReportLoadError("http", response.status);
      let payload: unknown;
      try {
        payload = await response.json();
      } catch (error) {
        throw new ReportLoadError(error instanceof SyntaxError ? "invalid" : "network");
      }
      return { response, payload };
    })();
    return await Promise.race([request, cancelled]);
  } finally {
    globalThis.clearTimeout(timer);
    externalSignal?.removeEventListener("abort", onAbort);
  }
}
