// End-to-end check of requirement atoms against e2e/fake_llm_server.py (default http://127.0.0.1:5098).
// Run: WORKBENCH_DATA_DIR=$(mktemp -d) python frontend/e2e/fake_llm_server.py & node e2e/atoms.mjs
import { chromium } from "playwright-core";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const base = process.argv[2] || "http://127.0.0.1:5098";
const shots = process.env.SHOTS || "";
const vttPath = join(mkdtempSync(join(tmpdir(), "wb-")), "Созвон по карточке.vtt");
writeFileSync(vttPath, "WEBVTT\n\n" +
  "00:00:01.000 --> 00:00:04.000\n<v SPEAKER_00>Карточка открывается не дольше двух секунд</v>\n\n" +
  "00:00:05.000 --> 00:00:08.000\n<v SPEAKER_01>Хватит и пяти секунд</v>\n\n" +
  "00:00:09.000 --> 00:00:12.000\n<v SPEAKER_00>Оператор видит историю заказов</v>\n\n" +
  "00:00:13.000 --> 00:00:16.000\n<v SPEAKER_01>А кто переносит старые обращения?</v>\n");

const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errors = [];
const EXPECTED_HTTP_ERRORS = [/\/summarize$/];
page.on("pageerror", e => errors.push(e.message));
page.on("response", r => {
  if (r.status() >= 400 && !EXPECTED_HTTP_ERRORS.some(re => re.test(new URL(r.url()).pathname)))
    errors.push(`${r.status()} ${r.url()}`);
});
const step = (name) => console.log("✓", name);
const shot = async (name) => { if (shots) await page.screenshot({ path: join(shots, name), fullPage: true }); };

await page.goto(base + "/#/atoms");
await page.getByText("Атомов пока нет").waitFor();
step("atoms screen has an empty state");

await page.goto(base + "/#/sources");
await page.locator('input[type=file]').setInputFiles(vttPath);
await page.getByRole("button", { name: "Импортировать и суммировать" }).click();
await page.getByText("Оператор видит историю заказов").waitFor();
await page.getByRole("button", { name: "Извлечь требования" }).click();
await page.getByRole("button", { name: "4 атома" }).waitFor({ timeout: 15000 });
step("extraction from the transcript screen");

await page.getByRole("button", { name: "4 атома" }).click();
await page.getByText("Только источник: Созвон по карточке").waitFor();
await page.getByRole("button", { name: "Показать все" }).click();
await page.getByText("4 на ревью · принято 0 из 4").waitFor();
await page.locator(".conflict", { hasText: "Разные требования к сроку" }).waitFor();
await shot("atoms.png");
step("atoms listed with counts and a conflict");

// Keyboard review: accept the selected (first) atom, reject the next.
await page.keyboard.press("a");
await page.getByText("3 на ревью · принято 1 из 4").waitFor();
await page.keyboard.press("x");
await page.getByText("2 на ревью · принято 1 из 4").waitFor();
await page.getByRole("status").getByRole("button", { name: "Отменить" }).click();
await page.getByText("3 на ревью · принято 1 из 4").waitFor();
step("keyboard accept / reject / undo");

// Edit a statement: the original wording stays visible.
await page.keyboard.press("e");
const area = page.locator(".atom textarea");
await area.fill("Карточка клиента открывается за 3 секунды");
await area.press("Enter");
await page.getByText("Исходная формулировка:").first().waitFor();
step("edit keeps the original wording");

// Resolve the conflict by turning it into a question for the client.
await page.locator(".conflict").getByRole("button", { name: "В вопрос" }).click();
await page.getByText("ждёт ответа заказчика").waitFor();
await page.getByRole("button", { name: /^вопросы/ }).click();
await page.locator(".atom", { hasText: "Уточнить у заказчика" }).waitFor();
step("conflict becomes a question");

// A quote opens the source at that line.
await page.getByRole("button", { name: /^все/ }).last().click();
await page.locator(".atom .quote", { hasText: "Хватит и пяти секунд" }).first().click();
await page.locator(".seg-row.flash", { hasText: "Хватит и пяти секунд" }).waitFor();
step("evidence quote jumps to the transcript line");

await page.goto(base + "/#/atoms");
await page.locator(".screen-sub", { hasText: "на ревью" }).waitFor();
for (let i = 0; i < 6; i++) await page.keyboard.press("a");
try { await page.getByText("Все атомы разобраны").waitFor({ timeout: 8000 }); }
catch (err) { await page.screenshot({ path: join(shots || tmpdir(), "atoms-fail.png"), fullPage: true }); throw err; }
await shot("atoms-done.png");
step("all reviewed state");

await browser.close();
if (errors.length) { console.error("page errors:", errors); process.exit(1); }
console.log("all atom steps passed");
