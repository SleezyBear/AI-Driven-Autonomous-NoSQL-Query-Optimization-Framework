import { expect, test } from "playwright/test";

test("the published frontend exposes the live run control-plane routes", async ({ page }) => {
  await page.goto("/runs");
  await expect(page.getByRole("heading", { name: "Runs" })).toBeVisible();
  await page.goto("/runs/new");
  await expect(page.getByRole("heading", { name: "Create optimization run" })).toBeVisible();
  await expect(page.getByLabel("Target ID")).toBeVisible();
  await expect(page.getByRole("button", { name: "Create run" })).toBeVisible();
});
