export const DEFAULT_ENGINE_ORIGIN = "http://127.0.0.1:8000";

function isLoopbackHostname(hostname: string): boolean {
  return hostname === "127.0.0.1" || hostname === "localhost";
}

export function normalizeEngineOrigin(input?: string | null): string {
  if (!input || input.trim() === "") {
    return DEFAULT_ENGINE_ORIGIN;
  }

  let url: URL;
  try {
    url = new URL(input);
  } catch {
    throw new Error("Engine origin must be a valid loopback URL");
  }

  if (url.protocol !== "http:" || !isLoopbackHostname(url.hostname)) {
    throw new Error("Engine origin must stay on a loopback http origin");
  }

  if (url.username || url.password) {
    throw new Error("Engine origin must not include credentials");
  }

  if (url.pathname && url.pathname !== "/") {
    throw new Error("Engine origin must not include a path");
  }

  if (url.search || url.hash) {
    throw new Error("Engine origin must not include search or hash fragments");
  }

  const portNumber = Number(url.port);
  if (
    url.port === "" ||
    !Number.isInteger(portNumber) ||
    portNumber < 1 ||
    portNumber > 65535
  ) {
    throw new Error("Engine origin must include an explicit valid port");
  }

  url.pathname = "";
  url.search = "";
  url.hash = "";
  return url.origin;
}

export function buildReportUrl(origin: string): string {
  return `${normalizeEngineOrigin(origin)}/research/report`;
}

export function buildEvidenceUrl(origin: string): string {
  return `${normalizeEngineOrigin(origin)}/evidence/`;
}
