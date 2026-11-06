# indream pipeline

Turns **one narration audio file + 2 to 4 images** into a finished 4K sleep video on GitHub Actions, then uploads it to YouTube with title, description, tags, chapters and a branded thumbnail.

The code never changes between videos. Each video is one folder, `jobs/<name>/`, holding its images and a `job.json` (the scene plan). Claude writes that `job.json` for you after looking at your images.

```
intro (10 s, 4K, animated title) -> scene 1 -> dissolve -> scene 2 -> dissolve -> scene 3 -> dissolve -> blue star-fly-through outro until ~4 h
                                    (looping animation: snow, fire, steam, twinkling stars, ...)
audio: intro swell + your narration + per-scene soft ambience (crossfades with the pictures) + long outro bed
```

## What is in here

| Path | What it is |
|---|---|
| `jobs/cabin-snow-001/` | the first video: 3 images + `job.json` |
| `jobs/_template/` | copy for new videos (or run `python -m engine.cli new --slug my-video`) |
| `brand/` | logo, title background, fonts, intro and outro settings. Built once, reused forever |
| `config/channel.json` | channel-wide settings: video quality, description footer, tags, YouTube options, and the locked thumbnail style (`thumbnail.style`, see `docs/THUMBNAIL_STYLE.md`) |
| `engine/` | the render, audio, thumbnail, metadata and upload code. You never edit this |
| `.github/workflows/` | the two buttons: **Build brand assets** and **Render and upload a video** |
| `vendor/animate.css` | the real animate.css 4.1.1 (MIT). The title entrance uses its keyframes |

## One-time setup (about 30 minutes)

**1. Create the repository.** New GitHub repo, upload everything in this zip. A *public* repo gives unlimited free Actions minutes and your keys stay safe in Secrets. A private repo has a monthly minute limit that 4K renders can use up.

**2. Allow the workflows to save files.** Repo, Settings, Actions, General, Workflow permissions, choose **Read and write permissions**, Save.

**3. YouTube access (do not paste these anywhere except GitHub Secrets).**
1. Google Cloud Console: create a project, enable **YouTube Data API v3**.
2. OAuth consent screen: type External, then press **Publish app** so it is "In production". If it stays in "Testing" the token dies after 7 days.
3. Credentials, Create credentials, OAuth client ID, type **Desktop app**, download the JSON as `client_secret.json`.
4. On your computer: `pip install google-auth-oauthlib` then `python tools/get_refresh_token.py client_secret.json`. Sign in with the account that owns the channel. It prints three values.
5. Repo, Settings, Secrets and variables, Actions, New repository secret. Add exactly: `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`.

**4. Build the intro and outro once.** Actions tab, **Build brand assets**, Run workflow. It renders the 10 second intro and the starry outro loop and saves them in a release called `brand-assets`. Every later video stitches them in automatically.

## About the intro picture

`brand/intro_bg.png` is your lakeside picture with the original baked-in "indream" text painted out, so the new logo can animate in on its own. There is a faint darker patch where the old text was, hidden by the logo glow and the grain. If you have the same picture without any text, replace that file and run **Build brand assets** again. Higher resolution is better: the current one is 1672 px wide and is enlarged to 4K.

## Adding the audio (it is too big for normal GitHub)

Your WAV is 363 MB and GitHub blocks files over 100 MB, so audio goes in a **release**:

1. Repo, Releases, **Draft a new release**.
2. Release title: the same name as in `job.json` under `audio.release` (for the first video: `cabin-snow-001`). For the tag, type anything, for example `audio-cabin-snow-001`.
3. Drag the audio file in. File name must match `audio.file` in `job.json` (`in_dream_cabin_snow_nico.wav`).
4. Click **Save draft**. Do not publish. A draft can only be seen by you, and the workflow can still download it.

## Making a video

1. Run **Render and upload a video**, job `cabin-snow-001`, tick **preview** first. In a few minutes you get a small test video plus `contact_sheet.jpg` to check the look.
2. Run it again with preview off. A 4 hour 4K video renders in roughly 1.5 to 3 hours. When done it uploads (private, see below) and saves the thumbnail, metadata and chapters as a downloadable artifact.

### Every new video

1. Send Claude the audio and images (2 to 4). Claude returns `jobs/<name>/job.json`.
2. In the repo create `jobs/<name>/` and upload the images plus `job.json` (Add file, Upload files).
3. Create the audio release (above) named as in the job.
4. Run the workflow. That is all.

## YouTube behaviour you should know

- Until Google approves your API project in its compliance audit, **every API upload is forced to Private**, whatever the settings say. The pipeline still uploads everything (video, thumbnail, title, description, tags, chapters, "not made for kids", language, category). You open YouTube Studio and press Schedule or Publish, about 30 seconds.
- After the audit passes, `job.json` `publish` controls it: `publish_after_hours: 24` uploads private and schedules public 24 hours later. If YouTube rejects the schedule, the pipeline keeps the video private and says so in the log.
- The API cannot pin comments, set monetisation, add end screens or choose the audience beyond "not made for kids". The suggested pinned comment is in `metadata.json`; pin it by hand.
- Custom thumbnails need your channel to be phone verified.
- The "altered or synthetic content" flag is set from `config/channel.json` (`contains_synthetic_media`). Set it honestly for what each video contains.

## Quality and size

- Output is 3840x2160 (true 4K UHD), 30 fps, H.264, 4K badge eligible. Change `fps` in `config/channel.json` if you ever want 24 or 25. Loops are rendered once (30 s) and repeated with stream copy, so hours of video cost minutes.
- Bitrate runs about 6 Mbps (video) so a 4 hour file is about 11 GB and fits on a free runner. To change it edit `crf` and `maxrate` in `config/channel.json`.
- The grain and paper texture are on every frame. Lower `grain` in a scene's `style` for a cleaner look, or higher for more texture.

## Troubleshooting

| Message | Fix |
|---|---|
| `No release named ...` | The audio release title must equal `audio.release` in the job file |
| `Release has no file ...` | The attached file name must equal `audio.file` |
| `Missing YT_CLIENT_ID ...` | Add the three secrets (step 3) |
| Upload works but video is private | Expected until the API audit passes, see above |
| Thumbnail `failed (403)` | Verify your channel by phone in YouTube Studio |
| Run stops with no space left | Re-run; if it repeats lower `maxrate` to `7M` |
| Want to see only the look | Run with **preview** ticked |

More detail on every `job.json` field and effect: `docs/JOB_REFERENCE.md`.
