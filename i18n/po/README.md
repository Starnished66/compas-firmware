# Translations

UI text is translated with gettext catalogs. English text in the C source is the
key: `TR("Text")` returns the translation for the active language, or the
English text when there is none. The catalogs live here (in compas-firmware, `i18n/po/`); the player's `src/ui/text/i18n/i18n_catalog.c`
(language list) and `i18n_catalog_<code>.c` (one table per language) are generated from them with `i18n/po2c.py` and checked in there, so a normal build needs no Python or
gettext.

## Updating or adding strings

1. Wrap user-visible text in the source (see "Rules" below).
2. In the player checkout `make i18n` extracts `po/compas.pot`, merges it into every `po/*.po` and
   regenerates `src/ui/text/i18n/i18n_catalog*.c`.
3. Translate the new (empty or fuzzy) entries in `po/<lang>.po`.
   Fuzzy entries are skipped until you remove the `fuzzy` flag.
4. `make i18n` again, then `make i18n-check` (stale template, bad printf
   conversions and unwrapped UI strings).

## Rules

- `TR("text")` at the place the text is shown. Format strings keep their
  placeholders: `TR("%d of %d")`. Translate whole sentences, never fragments.
- `TR_N("%d song", "%d songs", n)` when a count changes the wording.
- `TR_C("context", "text")` only when the same English word needs different
  translations; it maps to gettext `msgctxt`.
- `N_("text")` marks text in a static table; call `TR()` where it is displayed.
- Do not translate: log text, file names and paths, settings keys and values,
  protocol and API strings, text compared as data, plugin text, track metadata.
- Do not compare a label's text against a literal; compare state.
- Do not apply `toupper()` or other case changes to translated text.
- Buffers that receive translated text need room for longer wording.
- Intentional English that the checker flags goes in
  `scripts/i18n/untranslated_allow.txt`.

## Adding a language

1. Create `po/<code>.po` (for example
   `msginit --no-translator -i po/compas.pot -l pt -o po/pt.po`). Set the header fields `Language`,
   `X-Native-Name` (the language's own name, shown in the picker) and
   `Plural-Forms`.
2. Add the plural rule for the code in `i18n_plural_index()` in
   `src/ui/text/i18n/i18n.c` (Russian needs three forms; pt_BR and fr treat 0 as singular).
3. `make i18n`, translate, `make i18n-check`.
4. Check the fonts cover the language's characters (the Montserrat tiers cover
   Latin-1 and Latin Extended-A; other scripts need the fallback fonts).

The language list in Settings > System > Language comes from the catalogs, so
no UI code changes.

## Vietnamese and Japanese audio terminology

Use established player terminology consistently, while checking the actual UI
context. A library song count is not a metadata track number; the startup resume
setting means the last playback session, not the final track of an album.

| Meaning | Vietnamese | Japanese |
| --- | --- | --- |
| Play / playback | Phát / Phát lại | 再生 |
| Queue / playlist | Hàng đợi / Danh sách phát | キュー / プレイリスト |
| Shuffle | Phát ngẫu nhiên | シャッフル |
| Crossfade | Đan xen | クロスフェード |
| Equalizer / EQ band | Bộ chỉnh âm / Dải tần | イコライザー / バンド |
| Preamp / gain | Tiền khuếch đại / Độ lợi | プリアンプ / ゲイン |
| Sample rate | Tần số lấy mẫu | サンプルレート |
| Lyrics | Lời bài hát | 歌詞 |
| Album artwork | Ảnh bìa album | アートワーク |

Keep ReplayGain, PEQ, codec names, and protocol identifiers intact. Crossfeed
(クロスフィード in Japanese) is a separate DSP feature from crossfade. Japanese
library counts and next/previous-song controls use 曲; technical metadata and
ReplayGain track mode retain トラック. Keep translated labels concise enough for
the V1, and preserve printf argument order even when the conversions are identical.

Terminology references: [Apple Music Vietnamese playback settings](https://support.apple.com/vi-vn/guide/music-windows/musdf855a1b/windows),
[Vietnamese shuffle/repeat](https://support.apple.com/vi-vn/109332),
[Sony Vietnamese EQ bands](https://www.sony.com.vn/electronics/support/articles/00241283),
[Apple Music Japanese queue](https://support.apple.com/ja-jp/109336),
[Japanese EQ/preamp](https://support.apple.com/ja-jp/guide/music-windows/museb684a3de/windows),
and [Japanese artwork](https://support.apple.com/ja-jp/guide/music-windows/musa6e18cc25/windows).

## Regenerating the player catalog from this repository

```sh
COMPAS_PLAYER_DIR=../compas-player python3 i18n/po2c.py        # writes the player's i18n_catalog*.c
COMPAS_PLAYER_DIR=../compas-player python3 i18n/po2c.py --check # fails if it is stale
```

Run `--check` before packaging to verify that the player catalog matches these translations.
