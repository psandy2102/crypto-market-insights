import { describe, expect, it } from "vitest";
import { navigationItems } from "./navigation";

describe("dashboard navigation", () => {
  it("contains every planned workspace area", () => {
    expect(navigationItems.map((item) => item.label)).toEqual([
      "Overview",
      "Daily brief",
      "Chart",
      "News & events",
      "Outlook",
      "Performance",
      "Settings & health",
    ]);
  });
});
