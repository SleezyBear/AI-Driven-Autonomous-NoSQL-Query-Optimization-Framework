import { describe, expect, it } from "vitest";
import { ApiError, shouldRetryApiRequest } from "./client";

describe("API retry policy", () => {
  it("surfaces client authentication failures without retrying", () => {
    expect(shouldRetryApiRequest(0, new ApiError(401, "API request failed (401)"))).toBe(false);
    expect(shouldRetryApiRequest(0, new ApiError(403, "forbidden"))).toBe(false);
  });

  it("retains bounded retries for transient failures", () => {
    expect(shouldRetryApiRequest(0, new ApiError(503, "unavailable"))).toBe(true);
    expect(shouldRetryApiRequest(3, new Error("network failure"))).toBe(false);
  });
});
