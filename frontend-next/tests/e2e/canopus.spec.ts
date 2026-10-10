import { test, expect } from "@playwright/test";
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    if (!localStorage.getItem("suhail-ui-lab.preferences"))
      localStorage.setItem(
        "suhail-ui-lab.preferences",
        JSON.stringify({
          language: "en",
          theme: "light",
          motion: "reduce",
          density: "comfortable",
        }),
      );
  });
});
test("Canopus is global, inherits evidence context, and cited references focus the workspace", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  for (const route of ["operations", "decisions", "explore", "audit"]) {
    await page.goto(`/${route}`);
    await page
      .getByRole("button", { name: "Open Canopus assistant", exact: true })
      .click();
    await expect(page.getByRole("dialog")).toContainText("Canopus");
    await expect(page.getByRole("dialog")).toContainText(
      "Suhail operations assistant",
    );
    await page
      .getByRole("button", { name: "Minimize Canopus conversation" })
      .click();
  }
  await page.goto("/cases/SHP-10482");
  await page
    .getByRole("group", {
      name: "Contractor vehicle position · observation",
      exact: true,
    })
    .click();
  await page
    .getByRole("button", { name: "Open Canopus assistant", exact: true })
    .click();
  await expect(
    page.getByRole("combobox", { name: "Canopus shipment context" }),
  ).toContainText("SHP-10482");
  await page
    .getByRole("button", { name: "Expand conversation workspace" })
    .click();
  await expect
    .poll(async () => (await page.getByRole("dialog").boundingBox())!.width)
    .toBeGreaterThan(600);
  await page
    .getByRole("textbox", { name: "Ask Canopus" })
    .fill("@investigator explain the highlighted node");
  await page.getByRole("button", { name: "Send question" }).click();
  const transcript = page.getByRole("region", {
    name: "Canopus conversation transcript",
  });
  await expect(transcript).toContainText("Confirms vehicle position only");
  await expect(transcript).toContainText("Hypothesis · simulated");
  await expect(transcript).toContainText("Outcome · unverified");
  await page.screenshot({
    path: "screenshots/final-canopus-evidence.png",
    fullPage: false,
    animations: "disabled",
  });
  await transcript
    .getByRole("link", { name: "Contractor vehicle position", exact: true })
    .click();
  await expect(page).toHaveURL(/evidence=gps/);
  await expect(page.getByTestId("evidence-inspector")).toContainText(
    "vehicle position only",
  );
  await page
    .getByRole("button", { name: "Ask Suhail", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("region", { name: "Canopus conversation transcript" }),
  ).toContainText("Hypothesis · simulated");
  await expect(transcript).toContainText("Confirms vehicle position only");
  await transcript
    .getByRole("link", { name: "Review proposed action", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("Current assessment");
  await expect(page).toHaveURL(/section=assessment/);
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Close", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Open Canopus assistant", exact: true })
    .click();
  // The same citation must reopen its target after it has been dismissed.
  await transcript
    .getByRole("link", { name: "Review proposed action", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("Current assessment");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Close", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Open Canopus assistant", exact: true })
    .click();
  await transcript
    .getByRole("link", { name: "Decisions & authority", exact: true })
    .click();
  await expect(page).toHaveURL(/\/decisions\?case=SHP-10482/);
  await expect(page.getByRole("dialog")).toContainText("SHP-10482");
  expect(errors).toEqual([]);
});
test("Canopus presents retry feedback without changing a case or duplicating the question", async ({
  page,
}) => {
  await page.goto("/cases/SHP-10482");
  await page
    .getByRole("button", { name: "Open Canopus assistant", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Canopus conversation options" })
    .click();
  await page
    .getByRole("menuitem", { name: "Try a simulated response error" })
    .click();
  await expect(page.getByRole("alert")).toContainText("no case state changed");
  await page.reload();
  await page
    .getByRole("button", { name: "Open Canopus assistant", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("no case state changed");
  // A later question must not redirect Retry to a different reply.
  await page
    .getByRole("textbox", { name: "Ask Canopus" })
    .fill("Where is custody confirmed?");
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(
    page.getByRole("region", { name: "Canopus conversation transcript" }),
  ).toContainText("Last confirmed parcel custody");
  await page
    .getByRole("button", { name: "Retry response", exact: true })
    .click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(
    page.getByRole("region", { name: "Canopus conversation transcript" }),
  ).toContainText("policy C-04");
  await expect(
    page
      .getByRole("region", { name: "Canopus conversation transcript" })
      .locator('[data-slot="message"]'),
  ).toHaveCount(4);
  await page
    .getByRole("button", { name: "Minimize Canopus conversation" })
    .click();
  await expect(page.locator(".case-heading")).toContainText(
    "Awaiting approval",
  );
  await expect(
    page.locator('[data-sonner-toast][data-type="success"]'),
  ).toHaveCount(0);
});
test("Arabic Canopus works on mobile with localized replies and reduced motion", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/cases/SHP-10482");
  await page
    .getByRole("button", { name: "Switch to Arabic", exact: true })
    .click();
  await page
    .getByRole("button", { name: "فتح مساعد كانوبس", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveAttribute(
    "data-presentation",
    "floating",
  );
  await page
    .getByRole("textbox", { name: "اسأل كانوبس" })
    .fill("@reviewer لماذا يلزم تفويض المشغل؟");
  await page.getByRole("button", { name: "إرسال السؤال" }).click();
  await expect(
    page.getByRole("region", { name: "سجل محادثة كانوبس" }),
  ).toContainText("تفويضاً صريحاً");
  await expect(
    page.getByRole("region", { name: "سجل محادثة كانوبس" }),
  ).toContainText("فرضية · محاكاة");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    )
    .toBe(true);
  await expect(page.locator(".stream-cursor")).toHaveCount(0);
  await page.screenshot({
    path: "screenshots/final-canopus-arabic-mobile.png",
    fullPage: false,
    animations: "disabled",
  });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.goto("/explore");
  await page.getByRole("button", { name: "فتح مساعد كانوبس" }).click();
  await page
    .getByRole("button", { name: "اعرض الشحنات من الرياض إلى الخبر." })
    .click();
  await expect(page.getByTestId("explore-count")).toHaveText("8");
  await expect(
    page.getByRole("region", { name: "سجل محادثة كانوبس" }),
  ).toContainText("شحنات محاكاة مطابقة");
  await page
    .getByRole("button", { name: "تراجع عن التصفية", exact: true })
    .click();
  await expect(page.getByTestId("explore-count")).toHaveText("29");
});
