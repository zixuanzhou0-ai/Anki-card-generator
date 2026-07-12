import fs from "node:fs/promises";
import path from "node:path";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const reportRoot = "E:/ANKI/docs/reports/2026-06-24-cross-platform-verification";
const screenshots = "E:/ANKI/docs/screenshots";
const outputPptx = `${reportRoot}/Anki_Card_Generator_Cross_Platform_Verification.pptx`;
const previewDir = "C:/tmp/codex-presentations/manual-20260624/anki-card-generator-verification/tmp/preview";
const layoutDir = "C:/tmp/codex-presentations/manual-20260624/anki-card-generator-verification/tmp/layout";

const C = {
  ink: "#0B2545",
  blue: "#2563EB",
  cyan: "#0891B2",
  green: "#15803D",
  amber: "#A16207",
  red: "#B91C1C",
  slate: "#475569",
  muted: "#64748B",
  light: "#F8FAFC",
  band: "#EEF6FF",
  line: "#CBD5E1",
  white: "#FFFFFF",
};

async function writeBlob(filePath, blob) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, Buffer.from(await blob.arrayBuffer()));
}

async function imageBlob(filePath) {
  const bytes = await fs.readFile(filePath);
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
}

function text(slide, value, position, style = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position,
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = value;
  shape.text.style = {
    fontSize: style.fontSize ?? 20,
    bold: style.bold ?? false,
    color: style.color ?? C.ink,
    alignment: style.alignment ?? "left",
  };
  return shape;
}

function box(slide, position, fill = C.white, line = C.line, radius = "rounded-lg") {
  return slide.shapes.add({
    geometry: "roundRect",
    position,
    fill,
    line: { style: "solid", fill: line, width: 1 },
    borderRadius: radius,
  });
}

function title(slide, heading, eyebrow = "ANKI CARD GENERATOR VERIFICATION") {
  text(slide, eyebrow, { left: 72, top: 48, width: 520, height: 30 }, { fontSize: 16, bold: true, color: C.cyan });
  text(slide, heading, { left: 72, top: 86, width: 920, height: 70 }, { fontSize: 38, bold: true, color: C.ink });
}

function footer(slide, page) {
  text(slide, "v0.9.4-beta | Windows desktop release", { left: 72, top: 674, width: 520, height: 24 }, { fontSize: 16, color: C.muted });
  text(slide, String(page).padStart(2, "0"), { left: 1160, top: 674, width: 48, height: 24 }, { fontSize: 16, bold: true, color: C.muted, alignment: "right" });
}

function statusRow(slide, y, label, evidence, status, color = C.green) {
  box(slide, { left: 88, top: y, width: 220, height: 48 }, "#F8FAFC", C.line);
  text(slide, label, { left: 108, top: y + 12, width: 180, height: 24 }, { fontSize: 18, bold: true });
  text(slide, evidence, { left: 330, top: y + 8, width: 610, height: 32 }, { fontSize: 18, color: C.slate });
  box(slide, { left: 980, top: y + 6, width: 128, height: 36 }, "#FFFFFF", color);
  text(slide, status, { left: 1000, top: y + 13, width: 88, height: 20 }, { fontSize: 17, bold: true, color, alignment: "center" });
}

async function addImage(slide, filePath, position, alt, fit = "contain") {
  const ext = path.extname(filePath).toLowerCase();
  const contentType = ext === ".jpg" || ext === ".jpeg" ? "image/jpeg" : "image/png";
  slide.images.add({
    blob: await imageBlob(filePath),
    contentType,
    alt,
    fit,
    position,
    geometry: "roundRect",
    borderRadius: "rounded-lg",
  });
}

function bullet(slide, x, y, label, body, color = C.blue) {
  box(slide, { left: x, top: y, width: 330, height: 96 }, C.white, C.line);
  box(slide, { left: x + 18, top: y + 18, width: 34, height: 34 }, "#EFF6FF", color, "rounded-md");
  text(slide, label, { left: x + 68, top: y + 15, width: 230, height: 26 }, { fontSize: 20, bold: true, color: C.ink });
  text(slide, body, { left: x + 68, top: y + 47, width: 238, height: 38 }, { fontSize: 17, color: C.slate });
}

async function buildDeck() {
  const presentation = Presentation.create({ slideSize: { width: 1280, height: 720 } });

  let s = presentation.slides.add();
  s.background.fill = C.light;
  text(s, "Anki Card", { left: 72, top: 82, width: 520, height: 70 }, { fontSize: 58, bold: true, color: C.ink });
  text(s, "Generator", { left: 72, top: 154, width: 720, height: 70 }, { fontSize: 50, bold: true, color: C.blue });
  text(s, "v0.9.4-beta release verification, Windows desktop readiness, and Browser + Local Helper roadmap.", { left: 76, top: 254, width: 560, height: 92 }, { fontSize: 24, color: C.slate });
  box(s, { left: 740, top: 80, width: 420, height: 420 }, C.white, C.line);
  await addImage(s, `${screenshots}/desktop-workspace.png`, { left: 764, top: 112, width: 372, height: 300 }, "Desktop workspace screenshot", "contain");
  text(s, "Current conclusion: public Windows beta is usable; browser product remains a separate planned line.", { left: 766, top: 430, width: 368, height: 54 }, { fontSize: 21, bold: true, color: C.ink });
  footer(s, 1);

  s = presentation.slides.add();
  s.background.fill = C.white;
  title(s, "Release Verdict");
  text(s, "The core product is ready for Windows beta users. The only limited item is installed WebView2 CDP automation, which is observability, not a product failure.", { left: 74, top: 158, width: 980, height: 58 }, { fontSize: 22, color: C.slate });
  statusRow(s, 248, "GitHub", "About, README screenshots, Release labels", "PASS");
  statusRow(s, 312, "Assets", "Setup exe hash matches GitHub digest and SHA256SUMS", "PASS");
  statusRow(s, 376, "Tests", "Unit, UI, worker, Tauri build, release smoke", "PASS");
  statusRow(s, 440, "Install", "winget/ARP shows Anki Card Generator 0.9.4", "PASS");
  statusRow(s, 504, "CDP", "Installed WebView2 did not expose debug port", "LIMITED", C.amber);
  footer(s, 2);

  s = presentation.slides.add();
  s.background.fill = C.light;
  title(s, "What Users See on GitHub");
  bullet(s, 72, 188, "Windows first", "Release assets are Windows installer, MSI, and portable zip.", C.blue);
  bullet(s, 474, 188, "Clear checksum", "SHA256SUMS lets users verify downloaded files.", C.cyan);
  bullet(s, 876, 188, "Screenshots", "README shows workspace, settings, workflow, and Anki cards.", C.green);
  box(s, { left: 130, top: 360, width: 1020, height: 104 }, C.white, C.line);
  text(s, "Recommended README addition", { left: 160, top: 384, width: 360, height: 26 }, { fontSize: 22, bold: true, color: C.ink });
  text(s, "Add a 'Choose your build' block: Windows users download current Release; macOS/Linux users follow Browser + Local Helper roadmap.", { left: 160, top: 424, width: 850, height: 36 }, { fontSize: 20, color: C.slate });
  footer(s, 3);

  s = presentation.slides.add();
  s.background.fill = C.white;
  title(s, "Core Capability Pipeline");
  const steps = [
    ["Input", "Local video + SRT or video link"],
    ["Extract", "AI learning points and context"],
    ["Review", "User selects what becomes cards"],
    ["Generate", "Video, audio, TTS, explanations"],
    ["Verify", "APKG fields and media integrity"],
  ];
  for (const [i, step] of steps.entries()) {
    const x = 80 + i * 224;
    box(s, { left: x, top: 238, width: 180, height: 170 }, i % 2 ? "#F0FDFA" : "#EFF6FF", i % 2 ? C.cyan : C.blue);
    text(s, step[0], { left: x + 20, top: 270, width: 140, height: 30 }, { fontSize: 24, bold: true, color: C.ink, alignment: "center" });
    text(s, step[1], { left: x + 22, top: 320, width: 136, height: 52 }, { fontSize: 17, color: C.slate, alignment: "center" });
  }
  text(s, "Validated by worker tests, Playwright UI smoke, Tauri release build, and APKG smoke verification.", { left: 120, top: 484, width: 980, height: 36 }, { fontSize: 22, bold: true, color: C.green, alignment: "center" });
  footer(s, 4);

  s = presentation.slides.add();
  s.background.fill = C.light;
  title(s, "Screenshots Tell the User Story");
  await addImage(s, `${screenshots}/workflow-start.png`, { left: 76, top: 170, width: 350, height: 236 }, "Workflow start screenshot");
  await addImage(s, `${screenshots}/workflow-generated.png`, { left: 466, top: 170, width: 350, height: 236 }, "Generated workflow screenshot");
  await addImage(s, `${screenshots}/settings-tts.png`, { left: 856, top: 170, width: 350, height: 236 }, "TTS settings screenshot");
  text(s, "Public docs already show the full user journey: workspace, generation, settings, TTS, local environment, and final Anki cards.", { left: 120, top: 460, width: 1040, height: 58 }, { fontSize: 23, bold: true, color: C.ink, alignment: "center" });
  footer(s, 5);

  s = presentation.slides.add();
  s.background.fill = C.white;
  title(s, "Release Smoke Evidence");
  await addImage(s, `${screenshots}/anki-card-stress-middle.jpg`, { left: 780, top: 170, width: 330, height: 230 }, "Anki card screenshot");
  statusRow(s, 204, "Command", "npm.cmd run smoke:release", "PASS");
  statusRow(s, 268, "APKG", "1 note / 1 card generated and verified", "PASS");
  statusRow(s, 332, "Media", "MP4, WebM, poster, source audio, TTS audio", "PASS");
  statusRow(s, 396, "Integrity", "No missing, invalid, or unreferenced media", "PASS");
  text(s, "The smoke test uses synthetic media and fake cached TTS, so no real API key is exposed.", { left: 92, top: 514, width: 960, height: 40 }, { fontSize: 22, bold: true, color: C.ink });
  footer(s, 6);

  s = presentation.slides.add();
  s.background.fill = C.light;
  title(s, "Compact UI Regression Is Covered");
  bullet(s, 92, 194, "1180 x 780", "Minimum desktop size enters compact source-panel mode.", C.blue);
  bullet(s, 476, 194, "Reachable CTA", "Bottom action button stays visible or scroll-reachable.", C.green);
  bullet(s, 860, 194, "Batch picker", "Folder batch control can be reached and clicked.", C.cyan);
  box(s, { left: 150, top: 382, width: 980, height: 96 }, C.white, C.line);
  text(s, "Important nuance", { left: 182, top: 404, width: 260, height: 28 }, { fontSize: 23, bold: true, color: C.ink });
  text(s, "Installed WebView2 did not allow CDP automation, so installed-window screenshot is limited. The layout behavior itself is covered by Playwright UI smoke.", { left: 182, top: 440, width: 820, height: 32 }, { fontSize: 18, color: C.slate });
  footer(s, 7);

  s = presentation.slides.add();
  s.background.fill = C.white;
  title(s, "Browser + Local Helper Must Be Separate");
  bullet(s, 80, 210, "Windows desktop", "Tauri app owns current shipped product and native worker path.", C.blue);
  bullet(s, 475, 210, "Browser web", "Static UI, project flow, settings, and localhost helper calls.", C.cyan);
  bullet(s, 870, 210, "Local helper", "Files, ffmpeg, APKG export, AnkiConnect, cache, verify.", C.green);
  text(s, "Shared packages should stay narrow: types, card schema, and UI tokens only.", { left: 140, top: 458, width: 1000, height: 44 }, { fontSize: 24, bold: true, color: C.ink, alignment: "center" });
  footer(s, 8);

  s = presentation.slides.add();
  s.background.fill = C.light;
  title(s, "Tools and Plugins Used");
  const tools = [
    ["GitHub / gh CLI", "Release, assets, README, tags, digest"],
    ["Playwright", "UI smoke and minimum-size reachability"],
    ["documents", "Word report generation"],
    ["presentations", "Editable PowerPoint deck"],
    ["PowerShell / winget", "Install, process, hash, smoke commands"],
    ["Secret scan", "API key and artifact boundary checks"],
  ];
  for (const [i, item] of tools.entries()) {
    const x = i % 2 === 0 ? 100 : 650;
    const y = 178 + Math.floor(i / 2) * 118;
    box(s, { left: x, top: y, width: 470, height: 82 }, C.white, C.line);
    text(s, item[0], { left: x + 24, top: y + 16, width: 280, height: 24 }, { fontSize: 21, bold: true, color: C.ink });
    text(s, item[1], { left: x + 24, top: y + 48, width: 390, height: 24 }, { fontSize: 17, color: C.slate });
  }
  footer(s, 9);

  s = presentation.slides.add();
  s.background.fill = C.white;
  title(s, "Next Goals");
  text(s, "1. Publish clearer product routing: Windows Desktop now, Browser + Helper roadmap next.", { left: 120, top: 190, width: 980, height: 34 }, { fontSize: 24, color: C.ink });
  text(s, "2. Keep browser-web and local-helper in separate folders with explicit READMEs.", { left: 120, top: 252, width: 980, height: 34 }, { fontSize: 24, color: C.ink });
  text(s, "3. Define localhost helper API: health, settings, project, media, generate, export, verify.", { left: 120, top: 314, width: 980, height: 34 }, { fontSize: 24, color: C.ink });
  text(s, "4. Never upload API keys, APKGs, video/audio artifacts, test_runs, target, node_modules, or local caches.", { left: 120, top: 376, width: 980, height: 58 }, { fontSize: 24, bold: true, color: C.red });
  box(s, { left: 180, top: 498, width: 920, height: 64 }, "#F0FDF4", C.green);
  text(s, "The beta is useful now; the next leap is clean product separation.", { left: 210, top: 516, width: 860, height: 28 }, { fontSize: 25, bold: true, color: C.green, alignment: "center" });
  footer(s, 10);

  await fs.mkdir(previewDir, { recursive: true });
  await fs.mkdir(layoutDir, { recursive: true });
  for (const [index, slide] of presentation.slides.items.entries()) {
    const stem = `slide-${String(index + 1).padStart(2, "0")}`;
    await writeBlob(`${previewDir}/${stem}.png`, await presentation.export({ slide, format: "png", scale: 1 }));
    await fs.writeFile(`${layoutDir}/${stem}.layout.json`, await (await slide.export({ format: "layout" })).text());
  }
  await writeBlob(`${previewDir}/deck-montage.webp`, await presentation.export({ format: "webp", montage: true, scale: 1 }));
  const pptx = await PresentationFile.exportPptx(presentation);
  await pptx.save(outputPptx);
  console.log(JSON.stringify({ outputPptx, previewDir, layoutDir, slides: presentation.slides.items.length }, null, 2));
}

buildDeck().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});






