---
name: video-to-website
description: Turn a video into a premium scroll-driven animated website with GSAP, canvas frame rendering, and layered animation choreography.
---

# Video to Premium Scroll-Driven Website

Turn a video file into a scroll-driven animated website with **animation variety and choreography** — multiple animation types working together, not one repeated effect.

## Input

The user provides: a video file path (MP4, MOV, etc.) and optionally:
- A theme/brand name
- Desired text sections and where they appear
- Color scheme preferences
- Any specific design direction

If the user doesn't specify these, ask briefly or use sensible creative defaults.

## Premium Checklist (Non-Negotiable)

1. **Lenis smooth scroll** — native scroll feels "web page," Lenis feels "experience"
2. **4+ animation types** — never repeat the same entrance animation consecutively
3. **Staggered reveals** — label → heading → body → CTA, never all at once
4. **No glassmorphism cards** — text on clean backgrounds, hierarchy via font size/weight/color
5. **Direction variety** — sections enter from different directions (left, right, up, scale, clip)
6. **Dark overlay for stats** — 0.88-0.92 opacity, counters animate up, only time center text is OK
7. **Horizontal text marquee** — at least one oversized text element sliding on scroll (12vw+)
8. **Counter animations** — all numbers count up from 0, never appear statically
9. **Massive typography** — hero 12rem+, section headings 4rem+, marquee 10vw+
10. **CTA persists** — `data-persist="true"` keeps final section visible, never disappears
11. **Hero prominence + generous scroll** — hero gets 20%+ scroll range, 800vh+ total for 6 sections
12. **Side-aligned text ONLY** — all text in outer 40% zones (`align-left`/`align-right`), never center. Exception: stats with full dark overlay
13. **Circle-wipe hero reveal** — hero is standalone 100vh section, canvas reveals via `clip-path: circle()` as hero scrolls away
14. **Frame speed 1.8-2.2** — product animation completes by ~55% scroll. Below 1.8 feels sluggish
    — **BUT** when using frame-synced kinetic text (below), use **~1.0** instead so frames span the whole scroll.

## Two text systems (pick per project)
- **Section system (default):** side-aligned `data-enter/leave` sections (steps below). FRAME_SPEED 1.8–2.2;
  product finishes ~55% and sections continue over the held last frame.
- **Frame-synced kinetic text (great for short product clips / brand storytelling):** a single word/phrase
  pops IN then OUT every ~N frames, scrubbed to the frame index (reverses on scroll-up). **Centered is OK here**
  (overrides checklist #12 for these single words). **FRAME_SPEED ≈ 1.0.** See 6j. (PURE BLEND used this.)

## 21st.dev — REQUIRED for added sections
Beyond the canvas story, every site here must use **21st.dev Magic** (`/ui`, the `@21st-dev/magic` MCP) to add
premium sections — feature/bento grids, testimonials, logo clouds, pricing, refined CTAs. If the site is vanilla
(no React), take 21st.dev's structure + interaction (it returns React/Tailwind) and **reimplement in vanilla**,
restyled to the brand — never ship its defaults. Use `21st_magic_component_inspiration` to get usable design data.
(See `web.md`; PURE BLEND's Engineering bento came from the 21st.dev "divided feature grid" + cursor-glow patterns.)

## Workflow

**FFmpeg and FFprobe are on PATH — verify with `ffprobe -version`; do NOT reinstall.**
(Ignore any hardcoded `C:\Users\...\bin\` ffmpeg/Puppeteer paths left in older copies of this skill — call
`ffmpeg`/`ffprobe` directly.)

### Step 1: Analyze the Video

```bash
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,duration,r_frame_rate,nb_frames -of csv=p=0 "<VIDEO_PATH>"
```

Determine resolution, duration, frame rate, total frames. Decide:
- **Target frame count**: 150-300 frames for good scroll experience
  - Short video (<10s): extract at original fps, cap at ~300
  - Medium (10-30s): extract at 10-15fps
  - Long (30s+): extract at 5-10fps
- **Output resolution**: Match aspect ratio, cap width at 1920px

### Step 2: Extract Frames

```bash
mkdir -p frames
ffmpeg -i "<VIDEO_PATH>" -vf "fps=<CALCULATED_FPS>,scale=<WIDTH>:-1" -c:v libwebp -quality 80 "frames/frame_%04d.webp"
```

After extraction, count frames: `ls frames/ | wc -l`

### Step 3: Scaffold

```
project-root/
  index.html
  css/style.css
  js/app.js
  frames/frame_0001.webp ...
```

No bundler. Vanilla HTML/CSS/JS + CDN libraries.

### Step 4: Build index.html

Required structure (in this order):

```html
<!-- 1. Loader: #loader > .loader-brand, #loader-bar, #loader-percent -->
<!-- 2. Fixed header: .site-header > nav with logo + links -->
<!-- 3. Hero: .hero-standalone (100vh, solid bg, word-split heading) -->
<!--    Contains: .section-label, .hero-heading (words in spans), .hero-tagline -->
<!--    Scroll indicator with arrow -->
<!-- 4. Canvas: .canvas-wrap > canvas#canvas (fixed, full viewport) -->
<!-- 5. Dark overlay: #dark-overlay (fixed, full viewport, pointer-events:none) -->
<!-- 6. Marquee(s): .marquee-wrap > .marquee-text (fixed, 12vw font) -->
<!-- 7. Scroll container: #scroll-container (800vh+) -->
<!--    Content sections with data-enter, data-leave, data-animation -->
<!--    Stats section with .stat-number[data-value][data-decimals] -->
<!--    CTA section with data-persist="true" -->
```

Content section example:
```html
<section class="scroll-section section-content align-left"
         data-enter="22" data-leave="38" data-animation="slide-left">
  <div class="section-inner">
    <span class="section-label">002 / Feature</span>
    <h2 class="section-heading">Feature Headline</h2>
    <p class="section-body">Description text here.</p>
  </div>
</section>
```

Stats section example:
```html
<section class="scroll-section section-stats"
         data-enter="54" data-leave="72" data-animation="stagger-up">
  <div class="stats-grid">
    <div class="stat">
      <span class="stat-number" data-value="24" data-decimals="0">0</span>
      <span class="stat-suffix">hrs</span>
      <span class="stat-label">Cold retention</span>
    </div>
  </div>
</section>
```

CDN scripts (end of body, this order):
```html
<script src="https://cdn.jsdelivr.net/npm/lenis@1/dist/lenis.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/gsap@3/dist/ScrollTrigger.min.js"></script>
<script src="js/app.js"></script>
```

### Step 5: Build css/style.css

Use the **frontend-design skill** for creative, distinctive styling. Key technical patterns:

```css
:root {
  --bg-light: #f5f3f0;
  --bg-dark: #111111;
  --text-on-light: #1a1a1a;
  --text-on-dark: #f0ede8;
  --font-display: '[DISPLAY FONT]', sans-serif;
  --font-body: '[BODY FONT]', sans-serif;
}

/* Side-aligned text zones — product occupies center */
.align-left { padding-left: 5vw; padding-right: 55vw; }
.align-right { padding-left: 55vw; padding-right: 5vw; }
.align-left .section-inner,
.align-right .section-inner { max-width: 40vw; }
```

- **Hero-first layout**: Hero is standalone 100vh with solid bg. Canvas starts hidden, reveals via circle-wipe as hero scrolls away.
- **Scroll sections**: `position: absolute` within scroll container, positioned at midpoint of enter/leave range, `transform: translateY(-50%)`.
- **Mobile (<768px)**: Collapse side alignment to centered text with dark backdrop overlays. Reduce scroll height to ~550vh.
- **Text contrast**: Never use `#999` for important text on light backgrounds. Use `#666` minimum for body, `var(--text-on-light)` for headings.

### Step 6: Build js/app.js

#### 6a. Lenis Smooth Scroll (MANDATORY)

```js
const lenis = new Lenis({
  duration: 1.2,
  easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
  smoothWheel: true
});
lenis.on("scroll", ScrollTrigger.update);
gsap.ticker.add((time) => lenis.raf(time * 1000));
gsap.ticker.lagSmoothing(0);
```

#### 6b. Frame Preloader

Two-phase loading: load first 10 frames immediately (fast first paint), then load remaining frames in background. Show progress bar during load. Hide loader only after all frames are ready.

#### 6c. Canvas Renderer — Padded Cover Mode

```js
const IMAGE_SCALE = 0.85; // 0.82-0.90 sweet spot
function drawFrame(index) {
  const img = frames[index];
  if (!img) return;
  const cw = canvas.width, ch = canvas.height;
  const iw = img.naturalWidth, ih = img.naturalHeight;
  const scale = Math.max(cw / iw, ch / ih) * IMAGE_SCALE;
  const dw = iw * scale, dh = ih * scale;
  const dx = (cw - dw) / 2, dy = (ch - dh) / 2;
  ctx.fillStyle = bgColor; // sampled from frame corners
  ctx.fillRect(0, 0, cw, ch);
  ctx.drawImage(img, dx, dy, dw, dh);
}
```

- Auto-sample background color from frame edge pixels with `sampleBgColor()` every ~20 frames
- Fill canvas with sampled color BEFORE drawing (fills the thin padded border seamlessly)
- Apply devicePixelRatio scaling for crisp rendering
- Optional: edge feathering gradients for smoother blend (camera project uses this)

#### 6d. Frame-to-Scroll Binding

```js
const FRAME_SPEED = 2.0; // 1.8-2.2, higher = product animation finishes earlier
ScrollTrigger.create({
  trigger: scrollContainer,
  start: "top top",
  end: "bottom bottom",
  scrub: true,
  onUpdate: (self) => {
    const accelerated = Math.min(self.progress * FRAME_SPEED, 1);
    const index = Math.min(Math.floor(accelerated * FRAME_COUNT), FRAME_COUNT - 1);
    if (index !== currentFrame) {
      currentFrame = index;
      requestAnimationFrame(() => drawFrame(currentFrame));
    }
  }
});
```

#### 6e. Section Animation System

Each section reads `data-animation` and gets a different entrance. Sections with `data-persist="true"` stay visible once animated in. Position sections absolutely at the midpoint of their enter/leave range with `translateY(-50%)`.

```js
function setupSectionAnimation(section) {
  const type = section.dataset.animation;
  const persist = section.dataset.persist === "true";
  const enter = parseFloat(section.dataset.enter) / 100;
  const leave = parseFloat(section.dataset.leave) / 100;
  const children = section.querySelectorAll(
    ".section-label, .section-heading, .section-body, .section-note, .cta-button, .stat"
  );

  const tl = gsap.timeline({ paused: true });

  switch (type) {
    case "fade-up":
      tl.from(children, { y: 50, opacity: 0, stagger: 0.12, duration: 0.9, ease: "power3.out" });
      break;
    case "slide-left":
      tl.from(children, { x: -80, opacity: 0, stagger: 0.14, duration: 0.9, ease: "power3.out" });
      break;
    case "slide-right":
      tl.from(children, { x: 80, opacity: 0, stagger: 0.14, duration: 0.9, ease: "power3.out" });
      break;
    case "scale-up":
      tl.from(children, { scale: 0.85, opacity: 0, stagger: 0.12, duration: 1.0, ease: "power2.out" });
      break;
    case "rotate-in":
      tl.from(children, { y: 40, rotation: 3, opacity: 0, stagger: 0.1, duration: 0.9, ease: "power3.out" });
      break;
    case "stagger-up":
      tl.from(children, { y: 60, opacity: 0, stagger: 0.15, duration: 0.8, ease: "power3.out" });
      break;
    case "clip-reveal":
      tl.from(children, { clipPath: "inset(100% 0 0 0)", opacity: 0, stagger: 0.15, duration: 1.2, ease: "power4.inOut" });
      break;
  }

  // Play/reverse based on scroll position via ScrollTrigger onUpdate
  // If persist is true, never reverse when scrolling past the leave point
}
```

#### 6f. Counter Animations

```js
document.querySelectorAll(".stat-number").forEach(el => {
  const target = parseFloat(el.dataset.value);
  const decimals = parseInt(el.dataset.decimals || "0");
  gsap.from(el, {
    textContent: 0,
    duration: 2,
    ease: "power1.out",
    snap: { textContent: decimals === 0 ? 1 : 0.01 },
    scrollTrigger: { trigger: el.closest(".scroll-section"), start: "top 70%", toggleActions: "play none none reverse" }
  });
});
```

#### 6g. Horizontal Text Marquee

```js
document.querySelectorAll(".marquee-wrap").forEach(el => {
  const speed = parseFloat(el.dataset.scrollSpeed) || -25;
  gsap.to(el.querySelector(".marquee-text"), {
    xPercent: speed,
    ease: "none",
    scrollTrigger: { trigger: scrollContainer, start: "top top", end: "bottom bottom", scrub: true }
  });
  // Fade marquee in/out based on scroll range using opacity transitions
});
```

#### 6h. Dark Overlay

```js
function initDarkOverlay(enter, leave) {
  const overlay = document.getElementById("dark-overlay");
  const fadeRange = 0.04;
  ScrollTrigger.create({
    trigger: scrollContainer,
    start: "top top",
    end: "bottom bottom",
    scrub: true,
    onUpdate: (self) => {
      const p = self.progress;
      let opacity = 0;
      if (p >= enter - fadeRange && p <= enter) opacity = (p - (enter - fadeRange)) / fadeRange;
      else if (p > enter && p < leave) opacity = 0.9;
      else if (p >= leave && p <= leave + fadeRange) opacity = 0.9 * (1 - (p - leave) / fadeRange);
      overlay.style.opacity = opacity;
    }
  });
}
```

#### 6i. Circle-Wipe Hero Reveal

```js
function initHeroTransition() {
  ScrollTrigger.create({
    trigger: scrollContainer,
    start: "top top",
    end: "bottom bottom",
    scrub: true,
    onUpdate: (self) => {
      const p = self.progress;
      // Hero fades out as scroll begins
      heroSection.style.opacity = Math.max(0, 1 - p * 15);
      // Canvas reveals via expanding circle clip-path
      const wipeProgress = Math.min(1, Math.max(0, (p - 0.01) / 0.06));
      const radius = wipeProgress * 75; // 0% to 75% of viewport
      canvasWrap.style.clipPath = `circle(${radius}% at 50% 50%)`;
    }
  });
}
```

#### 6j. Frame-Synced Kinetic Text (optional — brand storytelling on short clips)

A single word/phrase pops **in then out** every ~N frames, scrubbed to the frame index so it
reverses perfectly on scroll-up. Use this instead of (or alongside) the section system when the clip
is short and the goal is a brand narrative over the render. **Requires `FRAME_SPEED ≈ 1.0`** so the
frames (and therefore the beats) span the whole scroll — otherwise the last beats never play.

```js
const FRAMES_PER_BEAT = 10;          // a new word every ~10 frames
const FRAME_END_AT    = 0.90;        // render finishes by 90% of scroll (leaves room for finale)
const FRAME_TEXTS = [                 // one beat per ~10-frame window (≈ FRAME_COUNT/10 beats)
  { kicker: "Introducing", html: "PURE <span class='em'>BLEND</span>" },
  { kicker: "It opens",    html: "Unsealed" },
  // … a beat with html:"" lets a composited/etched on-frame mark be the hero for that window
];

function easeOutCubic(t){ return 1 - Math.pow(1 - t, 3); }
function popValue(wp){                // wp 0..1 within a beat → 0..1 visibility
  const inEnd = 0.30, outStart = 0.70;
  let v = wp < inEnd ? wp/inEnd : wp > outStart ? 1-(wp-outStart)/(1-outStart) : 1;
  return easeOutCubic(Math.max(0, Math.min(1, v)));
}

// inside the frame ScrollTrigger onUpdate (same one that sets currentFrame):
const fp = Math.min(p / FRAME_END_AT, 1);
const floatFrame = fp * (FRAME_COUNT - 1);
const index = Math.min(Math.floor(floatFrame), FRAME_COUNT - 1);   // drives drawFrame
const beat = Math.min(Math.floor(floatFrame / FRAMES_PER_BEAT), FRAME_TEXTS.length - 1);
const wp   = (floatFrame - beat * FRAMES_PER_BEAT) / FRAMES_PER_BEAT;
if (beat !== currentBeat) { currentBeat = beat; /* swap kicker + innerHTML */ }
let vis = popValue(wp);
ftLayer.style.opacity   = vis;
ftLayer.style.transform = `translateY(${(1-vis)*26}px) scale(${0.72 + 0.28*vis})`;
ftLayer.style.filter    = `blur(${((1-vis)*7).toFixed(2)}px)`;
```

Legibility: give the text block a soft dark halo (`::before` radial-gradient behind it) so words
stay readable over any frame. Centered single words are fine here (overrides checklist #12).

#### 6k. Composited / Etched Brand on the Frames (Pillow)

When the render's product carries garbled AI "text" (Kling/Blender embossing) or you want the **brand
name physically on the product**, composite a clean wordmark onto every frame with Pillow *before*
building — it then moves/zooms with the product for free. Back up originals to `frames_orig/` first.

```python
from PIL import Image, ImageDraw, ImageFont, ImageFilter
MASK_BOX  = (846, 430, 1138, 580)     # region of the garbled AI text (per your video)
MASK_UNTIL = 72                        # only blur while the logo faces camera; later frames would smear fruit
FONT = ImageFont.truetype("georgiab.ttf", 64)
for i, path in enumerate(frame_paths):
    im = Image.open(path).convert("RGB")
    if i <= MASK_UNTIL:                # blur out the gibberish only where it's legible
        box = im.crop(MASK_BOX).filter(ImageFilter.GaussianBlur(18))
        im.paste(box, MASK_BOX)
    d = ImageDraw.Draw(im)             # draw the engraved-glass wordmark on ALL frames
    d.text((CX, LINE1_Y), "PURE",  font=FONT, fill=(235,235,235), anchor="mm")
    d.text((CX, LINE2_Y), "BLEND", font=FONT, fill=(235,235,235), anchor="mm")
    im.save(path, quality=90)
```

Gate the blur to the frames where the AI text is actually facing the camera (`MASK_UNTIL`) — blurring
late frames smears the product. Match font/opacity to the surface so it reads as etched, not pasted.

#### 6l. Brand-Reveal Zoom (push into the etched mark)

A short scroll window where the canvas scales up to showcase the on-product brand. Pair it with a
kicker-only beat (`html:""`) at the same window so the kinetic word doesn't fight the etched mark.

```js
const BRAND_REVEAL = { center: 0.14, half: 0.06, zoom: 0.26 };   // at 14% scroll, ±6%, +26% scale
const zt = Math.max(0, 1 - Math.abs(p - BRAND_REVEAL.center) / BRAND_REVEAL.half);
canvasWrap.style.transform = `scale(${(1 + BRAND_REVEAL.zoom * easeOutCubic(zt)).toFixed(3)})`;
// .canvas-wrap { transform-origin: 50% 48%; will-change: clip-path, transform }
```

### Step 7: Test

1. **Serve locally** from the site folder: `python -m http.server 3000` (or `npx serve . -l 3000`).
   Frames need HTTP — `file://` won't load them.
2. **Screenshot to verify** (this repo uses Playwright/Chromium via Python, not the `*.mjs` files some
   older notes mention). Expose the scroll engine for the shooter by adding `window.lenis = lenis;`
   after creating Lenis. Then drive it to exact scroll states:
   - Quick path: `python projects/website/screenshot.py http://localhost:3000 hero`.
   - Scroll-pinned canvas sites can't be captured in one full-page shot, so write a small Playwright
     script that, per shot, calls `window.lenis.scrollTo(y, { immediate: true })` then
     `window.ScrollTrigger.update()` and screenshots — target the **frame-ScrollTrigger progress**
     (e.g. `p=0.14` lands on the brand-reveal zoom) so you verify specific beats, not just pixels.
   - **Interpreter gotcha:** use a Python that actually has Playwright + Pillow + a Chromium install
     (here: `C:/Users/monar/AppData/Local/Python/pythoncore-3.14-64/python.exe`). A bare `python` may
     resolve to a project venv without them (`ModuleNotFoundError: playwright`).
   - Read the PNGs, fix mismatches, then delete the `temporary screenshots/` folder (gitignore it).
3. Scroll through fully — verify each section has a DIFFERENT animation type, OR (kinetic mode) a new
   word pops in→out every ~N frames and **reverses on scroll-up**.
4. Confirm: smooth scroll, frame playback, staggered reveals, marquee slides, counters count up, dark
   overlay fades, CTA persists at end, and (if used) the brand reads cleanly on the product — no AI
   gibberish or watermark left visible.

## Animation Types Quick Reference

| Type | Initial State | Animate To | Duration |
|------|--------------|-----------|----------|
| `fade-up` | y:50, opacity:0 | y:0, opacity:1 | 0.9s |
| `slide-left` | x:-80, opacity:0 | x:0, opacity:1 | 0.9s |
| `slide-right` | x:80, opacity:0 | x:0, opacity:1 | 0.9s |
| `scale-up` | scale:0.85, opacity:0 | scale:1, opacity:1 | 1.0s |
| `rotate-in` | y:40, rotation:3, opacity:0 | y:0, rotation:0, opacity:1 | 0.9s |
| `stagger-up` | y:60, opacity:0 | y:0, opacity:1 | 0.8s |
| `clip-reveal` | clipPath:inset(100% 0 0 0) | clipPath:inset(0% 0 0 0) | 1.2s |

All types use stagger (0.1-0.15s) and ease `power3.out` (except scale-up: `power2.out`, clip-reveal: `power4.inOut`).

## Anti-Patterns

- **Cycling feature cards in a pinned section** — each card gets too little scroll time. Give each feature its own scroll-triggered section (8-10% range) with its own animation type
- **Pure cover mode** (`Math.max` at 1.0) — product clips into header. Use `IMAGE_SCALE` 0.82-0.90
- **Pure contain mode** (`Math.min`) — leaves visible border that doesn't match page bg
- **FRAME_SPEED < 1.8** — product animation feels sluggish, use 1.8-2.2 — **EXCEPT** with frame-synced
  kinetic text (6j), where you deliberately use ~1.0 so the frames/beats span the whole scroll
- **Leaving AI gibberish or a watermark on the render** — Kling/Blender embossed "text" and the
  KlingAI corner watermark read as cheap. Mask the gibberish + composite a real wordmark (6k), and
  hide the watermark behind the canvas vignette
- **Frame-synced text with FRAME_SPEED > 1** — frames finish early, the later word beats never play
- **Blurring the masked logo region on every frame** — late frames (logo turned away) smear the
  product; gate the blur to the frames where the AI text faces the camera
- **Hero < 20% scroll range** — first impression needs breathing room
- **Same animation for consecutive sections** — never repeat the same entrance type back-to-back
- **Wide centered grids over canvas** — redesign as vertical lists in the 40% side zone
- **Scroll height < 800vh** for 6 sections — everything feels rushed

## Clip-Path Variations

- Circle reveal: `circle(0% at 50% 50%)` → `circle(75% at 50% 50%)`
- Wipe from left: `inset(0 100% 0 0)` → `inset(0 0% 0 0)`
- Wipe from bottom: `inset(100% 0 0 0)` → `inset(0% 0 0 0)`
- Custom polygon: `polygon(50% 0%, 50% 0%, 50% 100%, 50% 100%)` → `polygon(0% 0%, 100% 0%, 100% 100%, 0% 100%)`

## Troubleshooting

- **Frames not loading**: Must serve via HTTP, not `file://`
- **Choppy scrolling**: Increase `scrub` value, reduce frame count
- **White flashes**: Ensure all frames loaded before hiding loader
- **Blurry canvas**: Apply `devicePixelRatio` scaling to canvas dimensions
- **Lenis conflicts**: Ensure `lenis.on("scroll", ScrollTrigger.update)` is connected
- **Counters not animating**: Verify `data-value` attribute exists and snap settings match decimal places
- **Memory issues on mobile**: Reduce frames to <150, resize to 1280px wide
