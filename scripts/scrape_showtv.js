// scrape_channels.js
// Loads each target's live page in a headless browser and captures the
// real .m3u8 stream request the player makes. Needed because these
// stations' stream URLs are generated client-side by JavaScript and
// often include short-lived signed tokens -- a plain HTTP fetch of the
// page only returns static HTML and never sees the actual stream URL.
//
// Writes results to channels.json as { key: url, ... }. Any target that
// fails to produce a URL this run is simply omitted from the file, so
// merge.py can fall back to a static URL (or skip it) rather than crash.

const { chromium } = require('playwright');
const fs = require('fs');

const TARGETS = [
  { key: 'showtv',        page: 'https://www.showtv.com.tr/canli-yayin' },
  { key: 'tv2fyn',        page: 'https://www.tv2fyn.dk/live-tv' },
  { key: 'tv2nord',       page: 'https://www.tv2nord.dk/live' },
  { key: 'tvsyd',         page: 'https://www.tvsyd.dk/live-tv' },
  { key: 'tv2ostjylland', page: 'https://www.tv2ostjylland.dk/live-tv' },
  { key: 'tv2ost',        page: 'https://www.tv2east.dk/live' },              // NOTE: real domain is tv2east.dk, not tv2ost.dk
  { key: 'tvmidtvest',    page: 'https://www.tvmidtvest.dk/tv-midtvest-live' }, // different path structure than the others
  { key: 'tv2lorry',      page: 'https://www.tv2lorry.dk/live' },
];

const OUTPUT_FILE = 'channels.json';

async function scrapeOne(browser, target) {
  const page = await browser.newPage();
  let m3u8Url = null;

  page.on('request', (request) => {
    const url = request.url();
    if (!m3u8Url && url.includes('.m3u8')) {
      m3u8Url = url;
    }
  });

  try {
    await page.goto(target.page, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(6000);
  } catch (err) {
    console.error(`[${target.key}] page load issue (continuing anyway):`, err.message);
  }

  await page.close();
  return m3u8Url;
}

(async () => {
  const browser = await chromium.launch();
  const results = {};

  for (const target of TARGETS) {
    console.log(`Scraping ${target.key} (${target.page}) ...`);
    const url = await scrapeOne(browser, target);
    if (url) {
      results[target.key] = url;
      console.log(`  -> captured: ${url}`);
    } else {
      console.log(`  -> no .m3u8 request captured, skipping this run.`);
    }
  }

  await browser.close();

  fs.writeFileSync(OUTPUT_FILE, JSON.stringify(results, null, 2));
  console.log(`Wrote ${Object.keys(results).length}/${TARGETS.length} captured URLs to ${OUTPUT_FILE}`);
})();
