export function isArtifactRecord(
  value: unknown,
): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function matchesExpectedArtifactCapture(
  payload: Record<string, unknown>,
  expectedCapturedAt: string | undefined,
): boolean {
  if (!expectedCapturedAt) {
    return true;
  }
  const clocks = [payload.captured_at, payload.generated_at].filter(
    (value): value is string => typeof value === "string" && value.length > 0,
  );
  return clocks.length > 0 && clocks.every((value) => value === expectedCapturedAt);
}
