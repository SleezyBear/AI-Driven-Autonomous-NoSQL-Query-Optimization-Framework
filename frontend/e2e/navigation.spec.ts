import { expect, test } from "playwright/test";

test("the published frontend serves the target dashboard and its navigation", async ({ page }) => {
  await page.goto("/targets");
  await expect(page.getByRole("heading", { name: "Local monitored MongoDB" })).toBeVisible();
  await page.getByRole("link", { name: "Workload" }).click();
  await expect(page).toHaveURL(/\/workload$/);
  await expect(page.getByRole("heading", { name: "Monitored workload" })).toBeVisible();
});
