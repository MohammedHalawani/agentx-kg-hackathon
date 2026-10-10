import { test, expect, type Page } from "@playwright/test";

const launcher = (page: Page) =>
  page.getByRole("button", { name: /^(Open|Minimize) Canopus assistant$/ });
const window = (page: Page) =>
  page.getByRole("dialog", { name: "Canopus", exact: true });
const transcript = (page: Page) =>
  page.getByRole("region", {
    name: "Canopus conversation transcript",
    exact: true,
  });
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() =>
    localStorage.setItem(
      "suhail-ui-lab.preferences",
      JSON.stringify({
        theme: "light",
        language: "en",
        motion: "reduce",
        density: "comfortable",
      }),
    ),
  );
});

test("Floating Canopus has one launcher, focus tooltips, three states, and no workspace reflow", async ({
  page,
}) => {
  await page.goto("/cases/SHP-10482");
  await expect(
    page.getByTestId("knowledge-graph").locator(".react-flow__node").first(),
  ).toBeVisible();
  await expect
    .poll(() =>
      page.getByTestId("knowledge-graph").evaluate((el) => {
        const b = el.getBoundingClientRect();
        return [...el.querySelectorAll(".react-flow__node")].every((n) => {
          const r = n.getBoundingClientRect();
          return (
            r.left >= b.left - 1 &&
            r.right <= b.right + 1 &&
            r.top >= b.top - 1 &&
            r.bottom <= b.bottom + 1
          );
        });
      }),
    )
    .toBe(true);
  await expect(launcher(page)).toHaveCount(1);
  await expect(launcher(page)).toHaveAttribute("aria-expanded", "false");
  expect((await launcher(page).boundingBox())!.width).toBe(56);
  await page.screenshot({
    path: "screenshots/final-canopus-collapsed.png",
    animations: "disabled",
  });
  await launcher(page).hover();
  await expect(page.getByRole("tooltip")).toHaveText("Ask Canopus");
  await page.mouse.move(260, 10);
  await launcher(page).focus();
  await expect(page.getByRole("tooltip")).toHaveText("Ask Canopus");
  const map = await page.getByTestId("route-map").boundingBox();
  const graph = await page.getByTestId("knowledge-graph").boundingBox();
  await launcher(page).press("Enter");
  await expect(window(page)).toHaveAttribute("data-presentation", "floating");
  const floating = (await window(page).boundingBox())!;
  expect(floating.width).toBe(420);
  expect(floating.height).toBe(590);
  expect(floating.x + floating.width).toBe(1440 - 24);
  expect(floating.y + floating.height).toBeLessThan(
    (await launcher(page).boundingBox())!.y,
  );
  expect(await page.getByTestId("route-map").boundingBox()).toEqual(map);
  expect(await page.getByTestId("knowledge-graph").boundingBox()).toEqual(
    graph,
  );
  await expect(
    page.getByRole("textbox", { name: "Ask Canopus", exact: true }),
  ).toBeFocused();
  await page.screenshot({
    path: "screenshots/final-canopus-floating.png",
    animations: "disabled",
  });
  await page
    .getByRole("textbox", { name: "Ask Canopus", exact: true })
    .fill("Where is parcel custody confirmed?");
  await page
    .getByRole("button", { name: "Send question", exact: true })
    .click();
  await expect(transcript(page)).toContainText(
    "Last confirmed parcel custody:",
  );
  await expect(
    transcript(page).locator('[data-slot="message-group"]'),
  ).toHaveCount(2);
  await expect(
    transcript(page).getByText("Outcome · unverified", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "screenshots/final-canopus-floating-reply.png",
    animations: "disabled",
  });
  await page
    .getByRole("button", { name: "Expand conversation workspace", exact: true })
    .click();
  const expanded = (await window(page).boundingBox())!;
  expect(expanded.width).toBeGreaterThan(600);
  expect(Math.abs(expanded.x + expanded.width / 2 - 720)).toBeLessThan(2);
  expect(Math.abs(expanded.y + expanded.height / 2 - 450)).toBeLessThan(2);
  expect(await page.getByTestId("route-map").boundingBox()).toEqual(map);
  await page.screenshot({
    path: "screenshots/final-canopus-expanded.png",
    animations: "disabled",
  });
  await transcript(page).locator(".block-observation summary").click();
  await expect(
    transcript(page).locator(".block-observation > p"),
  ).toBeVisible();
  await transcript(page).locator(".block-outcome summary").focus();
  await transcript(page).locator(".block-outcome summary").press("Enter");
  await expect(transcript(page).locator(".block-outcome > p")).toContainText(
    "No independently verified outcome yet",
  );
  await page.keyboard.press("Escape");
  await expect(window(page)).not.toBeVisible();
  await expect(launcher(page)).toBeFocused();
  await launcher(page).press("Enter");
  await expect(window(page)).toHaveAttribute("data-presentation", "expanded");
  await page
    .getByRole("button", {
      name: "Collapse conversation workspace",
      exact: true,
    })
    .click();
  await expect(window(page)).toHaveAttribute("data-presentation", "floating");
  await page
    .getByRole("textbox", { name: "Ask Canopus", exact: true })
    .fill("@rev");
  await expect(page.getByRole("option", { name: /@reviewer/ })).toBeVisible();
  await page
    .getByRole("textbox", { name: "Ask Canopus", exact: true })
    .press("Escape");
  await expect(window(page)).toBeVisible();
  await expect(
    page.getByRole("option", { name: /@reviewer/ }),
  ).not.toBeVisible();
  await page.keyboard.press("Escape");
  await expect(launcher(page)).toBeFocused();
  await page
    .getByRole("group", {
      name: "Contractor vehicle position · observation",
      exact: true,
    })
    .click();
  await expect(page.getByTestId("evidence-inspector")).toContainText(
    "vehicle position only",
  );
  await page.locator(".evidence-marker").first().click();
  await expect(page.locator(".evidence-marker.selected")).toHaveCount(1);
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    )
    .toBe(true);
});

test("Minimizing preserves a long transcript's exact scroll position, selected context, and multiline draft", async ({
  page,
}) => {
  await page.addInitScript(() =>
    sessionStorage.setItem(
      "suhail-ui-lab.chat",
      JSON.stringify({
        "SHP-10479": Array.from({ length: 40 }, (_, i) => ({
          id: `saved-${i}`,
          role: i % 2 ? "assistant" : "user",
          agent: "suhail",
          text: `Previous exchange ${i}. The calibrated parcel weight observation is synthetic. Custody, a proposed action, and an independently verified result are separate.`,
          timestamp: "2026-10-09T10:00:00+03:00",
        })),
      }),
    ),
  );
  await page.goto("/operations");
  await launcher(page).click();
  await page
    .getByRole("combobox", { name: "Canopus shipment context", exact: true })
    .click();
  await page.getByRole("option", { name: "SHP-10479", exact: true }).click();
  await expect(transcript(page).locator('[data-slot="message"]')).toHaveCount(
    40,
  );
  await transcript(page).focus();
  await transcript(page).press("Control+Home");
  await expect
    .poll(() => transcript(page).evaluate((el) => el.scrollTop))
    .toBeLessThan(5);
  await transcript(page).hover();
  await page.mouse.wheel(0, 500);
  await expect
    .poll(() => transcript(page).evaluate((el) => el.scrollTop))
    .toBeGreaterThan(200);
  const editor = page.getByRole("textbox", {
    name: "Ask Canopus",
    exact: true,
  });
  await editor.fill("A draft to finish later");
  await editor.press("Shift+Enter");
  await expect(editor).toHaveValue("A draft to finish later\n");
  const position = await transcript(page).evaluate((el) => el.scrollTop);
  await page
    .getByRole("button", { name: "Minimize Canopus conversation", exact: true })
    .click();
  await expect(window(page)).not.toBeVisible();
  await expect(launcher(page)).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.locator(".canopus-window textarea")).not.toBeFocused();
  await launcher(page).click();
  await expect(
    page.getByRole("combobox", {
      name: "Canopus shipment context",
      exact: true,
    }),
  ).toContainText("SHP-10479");
  await expect(editor).toHaveValue("A draft to finish later\n");
  await expect(transcript(page).locator('[data-slot="message"]')).toHaveCount(
    40,
  );
  await expect
    .poll(() => transcript(page).evaluate((el) => el.scrollTop))
    .toBeGreaterThan(position - 2);
  await expect
    .poll(() => transcript(page).evaluate((el) => el.scrollTop))
    .toBeLessThan(position + 2);
  await expect(
    page.getByRole("button", { name: "Jump to latest", exact: true }),
  ).toHaveAttribute("data-active", "true");
  await page
    .getByRole("button", { name: "Jump to latest", exact: true })
    .click();
  await expect
    .poll(() =>
      transcript(page).evaluate(
        (el) => el.scrollHeight - el.scrollTop - el.clientHeight,
      ),
    )
    .toBeLessThan(60);
});

test("Canopus keeps case history through navigation and fits dark, RTL, mobile, and reduced-motion layouts", async ({
  page,
}) => {
  const appErrors: string[] = [];
  page.on("pageerror", (error) => appErrors.push(error.message));
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/settings");
  await page
    .getByRole("switch", { name: "Reduce motion", exact: true })
    .uncheck();
  await expect(page.locator("html")).toHaveAttribute("data-motion", "system");
  await page.goto("/cases/SHP-10482");
  await launcher(page).click();
  await page
    .getByRole("textbox", { name: "Ask Canopus", exact: true })
    .fill("Explain parcel custody");
  await page
    .getByRole("button", { name: "Send question", exact: true })
    .click();
  await expect(transcript(page)).toContainText("Outcome · unverified");
  // Navigate with the window open. The page context changes; earlier case history survives.
  await page
    .getByRole("link", { name: "Operations", exact: true })
    .first()
    .click();
  await expect(page.locator(".canopus-context")).toContainText("Operations");
  await page.getByRole("link", { name: "Investigation", exact: true }).click();
  await expect(transcript(page)).toContainText("Explain parcel custody");
  await expect(page.locator(".canopus-context")).toContainText("SHP-10482");
  await page.getByRole("button", { name: "Toggle theme", exact: true }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.screenshot({
    path: "screenshots/final-canopus-floating-dark.png",
    animations: "disabled",
  });
  await page
    .getByRole("button", { name: "Switch to Arabic", exact: true })
    .click();
  const arWindow = page.getByRole("dialog", { name: "Canopus", exact: true });
  const arLauncher = page.getByRole("button", {
    name: /^(فتح|تصغير) مساعد كانوبس$/,
  });
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  expect((await arLauncher.boundingBox())!.x).toBe(24);
  expect((await arWindow.boundingBox())!.x).toBe(24);
  await page.screenshot({
    path: "screenshots/final-canopus-arabic-desktop.png",
    animations: "disabled",
  });
  for (const viewport of [
    { width: 390, height: 844 },
    { width: 320, height: 568 },
    { width: 844, height: 390 },
  ]) {
    await page.setViewportSize(viewport);
    const box = (await arWindow.boundingBox())!;
    const composer = (await page
      .getByRole("textbox", { name: "اسأل كانوبس", exact: true })
      .boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.y).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
    expect(box.y + box.height).toBeLessThanOrEqual(viewport.height);
    expect(composer.y + composer.height).toBeLessThan(viewport.height);
    await expect
      .poll(() =>
        page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
      )
      .toBe(true);
    expect(
      await arWindow.evaluate((el) => getComputedStyle(el).transitionDuration),
    ).toBe("0s");
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "screenshots/final-canopus-floating-arabic-mobile.png",
    animations: "disabled",
  });
  await page.keyboard.press("Escape");
  await expect(arWindow).not.toBeVisible();
  await expect(arLauncher).toBeFocused();
  expect(appErrors).toEqual([]);
});
