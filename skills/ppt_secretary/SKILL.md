---
name: ppt_secretary
description: Real PNG rendering (single slide or a page range) and per-slide content reading for PowerPoint decks, via the aisecretary MCP tools (ppt_use_deck / ppt_get_deck / ppt_outline / ppt_get_slide / ppt_render_slide / ppt_render_pages).
---

# PPT Secretary

Use this skill when the user works on a PowerPoint deck: "把第 N 页发我一张截图", "这页讲了什么", "整份结构是什么", "这页是不是写得太满 / 怎么改".

Rendering is done by **LibreOffice inside aisecretary** — it is a real render, not a redraw of shapes. Never claim an approximation is a screenshot.

## Tools

| Tool | Purpose |
|------|---------|
| `ppt_use_deck` | Validate a `.pptx` path and remember it as the current deck |
| `ppt_get_deck` | Show the current deck (path, file name, slide count) |
| `ppt_outline` | Every slide's title + first body line, for a whole-deck overview |
| `ppt_get_slide` | One slide: title, text, tables, notes, image count, layout |
| `ppt_render_slide` | Render exactly one slide to PNG (2001×1125 @150dpi by default) |
| `ppt_render_pages` | Render several slides in one call — `pages="5-8"` or `"5,6,9"`; consecutive pages share one LibreOffice run |

All pages are **1-based**. Every tool returns JSON; on failure it returns `{"error": "<code>", "message": "..."}`.

## Flow

1. If you don't know the current deck, call `ppt_use_deck(path)` once — or pass `path` directly to the other tools.
2. One page → `ppt_render_slide(page)`.
3. Several pages ("第 5-8 页", "5、6、9 页") → **one** `ppt_render_pages(pages="5-8")` call, not a loop of `ppt_render_slide`. Consecutive pages share a single LibreOffice run (~2.8s for 4 pages vs ~4.2s one by one).
4. Content question → `ppt_get_slide(page)` first; render only if the user also needs to see it.
5. Whole-deck structure → `ppt_outline()`.

Paths must be absolute and under the allowed deck directory. If the tool returns `path_not_allowed` or `deck_not_found`, ask the user for the correct absolute path instead of guessing.

## Sending the image

Reply with the returned path on its own line as:

```
MEDIA:<path returned by ppt_render_slide / ppt_render_pages>
```

Use the path **verbatim**. Without the `MEDIA:` prefix Feishu sends a file attachment instead of an image message.

For several pages, emit one `MEDIA:` line per returned item, in page order, and label them (e.g. `第 5 页 / 共 64 页`).

## Rules

- Page out of range: run the tool, then tell the user the total slide count (`slide_count` in the error). Never silently clamp.
- Do not describe visual details you did not get from the tools. You cannot see the PNG — it is for the user.
- Do not over-explain when the user only asked for a screenshot.
- Rendering takes ~1-2s per page (≈5s for a batch of 8); repeats hit the cache instantly. If a render times out, say so and offer to retry.
- At most 32 pages per call; for a bigger range, split the request into batches instead of aborting.
- The deck is the source of truth. Never reconstruct slides with code, and never ask for a whole-deck export — only explicit page ranges are rendered.
- Interpretation is yours (Hermes). aisecretary has no LLM and stores no model keys.
- When the user asks "怎么改", base the answer on the actual text/tables/notes from `ppt_get_slide`, not on imagination.

## Errors

| Code | Meaning | What to do |
|------|---------|------------|
| `no_deck` | No deck selected | Ask for the path, then `ppt_use_deck` |
| `deck_not_found` | Path missing / file moved | Ask the user for the current path |
| `not_pptx` | Not a PowerPoint file / broken file | Tell the user only `.pptx` is supported |
| `path_not_allowed` | Outside the allowed directory | Ask for a path under the deck directory |
| `slide_out_of_range` | Page beyond `slide_count` | Report the total page count |
| `render_unavailable` | Image lacks LibreOffice | Tell the user the deployment needs the PPT-enabled image |
| `render_timeout` | Render exceeded the budget | Retry once, then report failure |
| `render_failed` | LibreOffice failed on this deck | Report it; suggest checking the file opens in PowerPoint |
