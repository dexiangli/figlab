// 找一个可用的 Chromium 内核浏览器（Edge / Chrome），供 CDP 交互测试用。
// 换机器不用改代码：优先读环境变量 FIGLAB_BROWSER，其次探常见安装位置。
import { existsSync } from "node:fs";

const CANDIDATES = [
  process.env.FIGLAB_BROWSER,
  process.env.EDGE_PATH,
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/microsoft-edge",
  "/usr/bin/microsoft-edge-stable",
  "/usr/bin/google-chrome",
  "/usr/bin/google-chrome-stable",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
];

export function findBrowser() {
  for (const c of CANDIDATES) {
    if (c && existsSync(c)) return c;
  }
  console.error(
    "找不到 Edge / Chrome，UI 测试需要本机装一个 Chromium 内核浏览器。\n" +
    "也可以手动指定，例如：\n" +
    "  Windows PowerShell:  $env:FIGLAB_BROWSER=\"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe\"\n" +
    "  macOS / Linux:       export FIGLAB_BROWSER=/usr/bin/google-chrome\n" +
    "（只影响 tests/*.mjs 这些交互测试；平台本身不用 Node、也不用浏览器。）"
  );
  process.exit(2);
}
