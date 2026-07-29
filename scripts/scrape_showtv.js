// scrape_showtv.js
// Loads Show TV's live page in a headless browser and captures the real
// .m3u8 request the player makes. This is necessary because the stream
// URL includes a short-lived signed token (ex=, st=, sid=, app=, ce=)
// generated client-side by JavaScript -- a plain HTTP fetch of the page
// only returns static HTML and never sees this URL.
//
// Writes the captured URL to showtv_url.txt (one line). If nothing is
// captured (page structure changed, stream down, etc.), the file is
// left untouched so merge.py can fall back to the last known URL.

const { chromium } = require('playwright');
const fs = require('fs');

const TARGET_PAGE = 'https://www.showtv.com.tr/canli-yayin';
const OUTPUT_FILE = 'showtv_url.txt';

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  let m3u8Url = null;

  page.on('request', (request) => {
    const url = request.url();
    if (!m3u8Url && url.includes('.m3u8')) {
      m3u8Url = url;
    }
  });

  try {
    await page.goto(TARGET_PAGE, { waitUntil: 'networkidle', timeout: 30000 });
    // Give the player a few seconds to initialize and request the stream.
    await page.waitForTimeout(6000);
  } catch (err) {
    console.error('Page load issue (continuing anyway):', err.message);
  }

  await browser.close();

  if (m3u8Url) {
    fs.writeFileSync(OUTPUT_FILE, m3u8Url.trim() + '\n');
    console.log('Captured fresh Show TV URL:', m3u8Url);
  } else {
    console.log('No .m3u8 request captured this run -- leaving showtv_url.txt unchanged.');
  }
})();
