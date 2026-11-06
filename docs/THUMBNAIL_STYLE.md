# indream thumbnail style

Every thumbnail uses one locked look so the channel is recognisable at a glance, even in a crowded feed.

**The signature**
- Big Title Case serif title (Cormorant Garamond bold, e.g. *Fall Asleep by the Fire*), top-left, in warm white with a dark halo and soft amber glow
- **One gold word** in every title (the idea you want people to feel: *fire*, *snow*, *warm*)
- Italic gold subtitle underneath, always `sleep story · N hours` (the hours come from `total_hours`)
- Small gold crescent `indream` logo, always top-right
- Warm bloom on the lights, darker left side so the title is always readable

**Per video you only decide**
```
"thumbnail": {"scene": 2, "title": "fall asleep by the fire", "accent": "fire", "focus": [0.52, 0.5], "zoom": 1.12}
```
- `scene`: which picture (position in `scenes`, starting at 0). Pick the one with the strongest warm light.
- `title`: 2 to 5 words. Write it in any case, capitals are added automatically. Change `thumbnail.style.title.case` in `config/channel.json` to `words` (every word capitalised), `lower` or `upper`. More than 3 lines is cut. If a line is too wide the text shrinks by itself so it never reaches the picture's subject.
- `accent`: the gold word (or a list of words). Leave it out and the last word is used.
- `focus` / `zoom`: where to crop. Keep the subject on the right half, the title owns the left.

**Changing the brand for the whole channel**: edit `thumbnail.style` in `config/channel.json` once. Colours, size, position, logo corner and subtitle wording all live there. The one-off escape hatch `"override": {...}` inside a job exists but breaks the family look, so avoid it.
