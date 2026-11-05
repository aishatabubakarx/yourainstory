# job.json reference

All positions are fractions of the picture: `[0,0]` top-left, `[1,1]` bottom-right. A box is `[left, top, right, bottom]`.

```
slug            folder name, also used for the output
title_short     plain title (used for the thumbnail default)
audio           where the narration is. One of:
                  {"source":"release","release":"<release title>","file":"<file name>"}
                  {"source":"file","path":"audio.wav"}          (small files kept in the job folder)
                  {"source":"url","url":"https://..."}
total_hours     length of the whole video (narration + outro). 4.0 means about 4 hours
ambience        {"under_voice_db": -4, "outro_db": 4}  quieter/louder background sound while narrating / after
scenes[]        2 to 4 scenes, equal share of the narration each, in order
  name, chapter, image
  ambience      {"wind":0-1, "hush":0-1, "rain":0-1, "fire":0-1}  how much of each sound in this scene
  effects[]     see below
  style         optional {"dim":0.92,"vignette":0.22,"paper":0.035,"grain":2.4}
outro           {"ambience": {...}} sound under the starry outro
thumbnail       {"scene":index, "title":"short title", "accent":"one gold word", "focus":[x,y], "zoom":1.1}
                the LOOK (fonts, colours, glow, logo, "sleep story · N hours") is fixed for the channel, see docs/THUMBNAIL_STYLE.md
publish         {"privacy":"private","publish_after_hours":24}   or "publish_at":"2026-12-01T20:00:00Z"
metadata        title (max 100), hook (first 2 lines people see), about, keywords_paragraph,
                hashtags (first 3 show above the title), tags, pinned_comment
```

## Effects

| type | what it does | main settings |
|---|---|---|
| `snow` | seamless falling snow in 3 depths | `count` (flakes), `wind` (0-1), `size`, `speed`, `mask`: `{"box":[...]}` keeps snow inside window panes only |
| `flicker` | simple warm light pulse for lanterns and lit windows. For fireplaces and candles use `fire` | `box`, `amp` strength, `rate` Hz, `glow` room light, `warp` flame wobble, `threshold` brightness |
| `fire` | natural fireplace or candle: flames lick upward, the inside of the flame shimmers, warm light drifts softly over the stone and wood around it, a few embers rise (fire only) | `box` around the flames, `base` (y where the flame starts, 0 to 1), `height` (flame height as a fraction of the picture height), `kind`: `fire` (default) or `candle`, `threshold` (how bright a pixel must be to count as flame, default 0.55), `lick` (how far flames bend), `speed`, `shimmer`, `sway` (slow lean), `light` (strength of the room light), `light_radius`, `embers` (0 to switch off), `rate` (light pace in Hz, keep below 1 for a calm look) |
| `steam` / `smoke` | rising puffs | `origin`, `rise`, `drift`, `sway`, `size0`, `size1`, `count`, `cycles`, `alpha`, `color` |
| `sway` | gently bends a region (existing smoke, leaves, banners) | `box`, `anchor` bottom/top/none, `amp`, `rate`, `wavelength` |
| `ripple` | water shimmer | `box`, `amp`, `rate`, `wavelength` |
| `twinkle` | finds stars or lights in a box and makes them breathe | `box`, `count`, `amp` |
| `starfield` | fly-through stars streaming outward, as if gliding forward (outro) | `count`, `cycles`, `trail`, `center`, `glow`, `palette` |
| `fog` | slowly moving coloured mist (outro style) | `color`, `strength`, `center`, `cells` |

Every motion repeats exactly once per loop, so the loop has no visible seam.
