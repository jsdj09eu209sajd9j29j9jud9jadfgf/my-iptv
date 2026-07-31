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
  { key: 'tvmidtvest',    page: 'https://www.tvmidtvest.dk/tv-kanalen' },
  { key: 'tv2lorry',      page: 'https://www.tv2lorry.dk/live' },
  { key: 'drramasjang',   page: 'https://www.dr.dk/drtv/kanal/dr-ramasjang_20892' },
  // Backup for Cartoon Network in case the yt-dlp extraction step fails
  // (YouTube sometimes blocks yt-dlp's request as a bot from datacenter
  // IPs like GitHub Actions runners) -- a real headless browser session
  // sometimes gets through where a raw API call doesn't.
  { key: 'cartoonnetwork_yt', page: 'https://www.youtube.com/live/LwKF_GkaNF4' },
];

const OUTPUT_FILE = 'channels.json';

async function scrapeOne(browser, target) {
  const page = await browser.newPage();
  let streamUrl = null;

  page.on('request', (request) => {
    if (streamUrl) return; // already found this run
    const url = request.url();

    // JWPlayer's analytics beacon (jwpltx.com/.../ping.gif) reliably
    // embeds the REAL manifest URL in its "mu" query parameter -- this
    // fires even when we can't get the actual player to start, so it's
    // actually a more reliable signal than waiting for the real request.
    if (url.includes('jwpltx.com') && url.includes('ping.gif')) {
      try {
        const mu = new URL(url).searchParams.get('mu');
        if (mu && (mu.includes('.m3u8') || mu.includes('.mpd'))) {
          streamUrl = mu;
        }
      } catch {
        // malformed URL -- ignore
      }
      return; // never treat the ping itself as the stream, even if unparsed
    }

    // Direct manifest requests (the real thing, when it does fire).
    if (url.includes('.m3u8') || url.includes('.mpd')) {
      streamUrl = url;
    }

    // Debug visibility: log anything that looks stream-related even if
    // it doesn't match above, so failures are diagnosable from the log.
    if (/\.(m3u8|mpd)(\?|$)|\/manifest|\/playlist\.|\/hls\/|\/dash\//i.test(url)) {
      console.log(`  [debug] saw request: ${url}`);
    }
  });

  try {
    await page.goto(target.page, { waitUntil: 'networkidle', timeout: 30000 });

    // Many Danish news sites block the video player behind a cookie
    // consent wall -- the player never requests the stream until consent
    // is dismissed. Try a handful of common "accept" button patterns.
    const consentSelectors = [
      'button:has-text("Acceptér alle")',
      'button:has-text("Accepter alle")',
      'button:has-text("Accepter alt")',
      'button:has-text("Tillad alle")',
      'button:has-text("Godkend alle")',
      '#onetrust-accept-btn-handler',
      '.cm-btn-accept-all',
      '[data-testid="accept-all"]',
    ];
    for (const sel of consentSelectors) {
      try {
        const btn = page.locator(sel).first();
        if (await btn.isVisible({ timeout: 2000 })) {
          await btn.click({ timeout: 2000 });
          console.log(`[${target.key}] dismissed cookie consent via "${sel}"`);
          break;
        }
      } catch {
        // selector not present/visible -- try the next one
      }
    }

    // Give the player a chance to init/start after consent is cleared.
    await page.waitForTimeout(6000);

    // Some pages lazy-load the player only once it's actually scrolled
    // into view. Try nudging it into view if we still have nothing.
    if (!streamUrl) {
      try {
        const video = page.locator('video, [class*="player" i]').first();
        if (await video.count() > 0) {
          await video.scrollIntoViewIfNeeded({ timeout: 2000 });
          console.log(`[${target.key}] scrolled player into view`);
        }
      } catch {
        // no such element, or scroll failed -- continue anyway
      }
      await page.waitForTimeout(4000);
    }

    // Some players need a click to start (autoplay policies). Try
    // clicking a generic play button / video element if still nothing.
    if (!streamUrl) {
      const playSelectors = ['button[aria-label*="play" i]', '.jw-icon-playback', 'video'];
      for (const sel of playSelectors) {
        try {
          const el = page.locator(sel).first();
          if (await el.isVisible({ timeout: 1500 })) {
            await el.click({ timeout: 1500, force: true });
            console.log(`[${target.key}] clicked play via "${sel}"`);
            break;
          }
        } catch {
          // not present -- try next
        }
      }
      await page.waitForTimeout(6000);
    }

    // Fallback: if no network request was ever captured (e.g. autoplay
    // never actually triggered in headless mode), scan the raw page
    // HTML/inline scripts for an embedded JWPlayer stream URL or media
    // ID -- this is often present as plain text even if playback never
    // starts, since jwplayer.setup({...}) configs are inlined in <script>
    // tags rather than fetched dynamically.
    if (!streamUrl) {
      try {
        const html = await page.content();
        const directMatch = html.match(/https:\/\/content\.jwplatform\.com\/live\/broadcast\/[A-Za-z0-9]+\.m3u8[^"'\s\\]*/);
        if (directMatch) {
          streamUrl = directMatch[0];
          console.log(`[${target.key}] found stream URL embedded in page HTML: ${streamUrl}`);
        } else {
          const idMatch = html.match(/jwplatform\.com\/(?:live\/broadcast|videos|players)\/([A-Za-z0-9]{6,10})/)
            || html.match(/["']mediaid["']\s*:\s*["']([A-Za-z0-9]{6,10})["']/);
          if (idMatch) {
            streamUrl = `https://content.jwplatform.com/live/broadcast/${idMatch[1]}.m3u8`;
            console.log(`[${target.key}] constructed stream URL from embedded media ID: ${streamUrl}`);
          }
        }
      } catch (err) {
        console.error(`[${target.key}] HTML scan failed:`, err.message);
      }
    }
  } catch (err) {
    console.error(`[${target.key}] page load issue (continuing anyway):`, err.message);
  }

  await page.close();
  return streamUrl;
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
