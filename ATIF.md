# Atıf ve lisans notları

Bu klasördeki paketler yalnızca özetlenmiş anahtarlar (SHA-256) ve Türkçe metin içerir; oyun metni yoktur.
Aşağıdaki kaynak satırları paket dosyalarının içindeki `source` alanından, atıf metinleri
özgün hâliyle `atif-ek.md` dosyasından aktarılmıştır.

## Paketlerin kaynağı (paketlerin `source` alanı)

- `assassins-creed-shadows` (Assassin's Creed Shadows): Claude Haiku 5.5, 2026-11-11 + Claude Opus 5.5, 2026-11-21
- `call-of-duty-modern-warfare-2019` (Call of Duty: Modern Warfare (2019)): Claude Haiku 5.5, 2026-11-11 + Claude Opus 5.5, 2026-11-21
- `death-stranding-2` (Death Stranding 2: On the Beach): Claude Haiku 5.5, 2026-11-11 + Claude Opus 5.5, 2026-11-21
- `death-stranding-directors-cut` (Death Stranding Director's Cut): Claude Haiku 5.5, 2026-11-12; English text: Game Scripts Wiki fan transcript
- `elden-ring` (Elden Ring + Shadow of the Erdtree): Claude Haiku 5.5, 2026-11-11 + Claude Opus 5.5, 2026-11-21; English text: Carian Archive, Impaler's Archive
- `gta-6` (Grand Theft Auto VI): CouchSubs havuzu (en az 2 oyuncu) + Workers AI (@cf/zai-org/glm-5.3-flash) + PR #387 (lones8888: YouTube oynanışından OCR, Codex/Gemma çevirisi) + PR #614 (lones8888: elle düzeltilmiş topluluk havuzu, öncelikli) + Claude Opus 5.5, 2026-11-21 + oyun metni dökümü (Xbox 1.0.2.1), Claude Opus 5.5, 2026-11-22; ek satırlar: CouchSubs havuzu (en az 2 oyuncu) + Claude (claude-opus-5-5) / Workers AI (@cf/zai-org/glm-5.3-flash)
  - ek satırlar `pool-gta-6` paketinden birleştirildi; kaynağı: CouchSubs havuzu (en az 2 oyuncu) + Claude (claude-opus-5-5) / Workers AI (@cf/zai-org/glm-5.3-flash)
- `gta-v` (Grand Theft Auto V): GTA TR (TechnoGame) + Claude Haiku 5.5; ek satırlar: CouchSubs havuzu (en az 2 oyuncu) + Claude (claude-opus-5-5) / Workers AI (@cf/zai-org/glm-5.3-flash)
  - ek satırlar `pool-gta-5` paketinden birleştirildi; kaynağı: CouchSubs havuzu (en az 2 oyuncu) + Claude (claude-opus-5-5) / Workers AI (@cf/zai-org/glm-5.3-flash)
- `mafia-the-old-country` (Mafia: The Old Country): Claude Fable 5.1, 2026-11-11 + Claude Opus 5.5, 2026-11-21
- `marvels-spider-man-2` (Marvel's Spider-Man 2): Claude Haiku 5.5, 2026-11-12 + Claude Opus 5.5, 2026-11-21; English text: Marvel's Spider-Man Wiki (CC BY-SA) + CouchSubs subtitle pool; ek satırlar: CouchSubs havuzu (en az 2 oyuncu) + Claude (claude-opus-5-5) / Workers AI (@cf/zai-org/glm-5.3-flash)
  - ek satırlar `pool-marvels-spider-man-2` paketinden birleştirildi; kaynağı: CouchSubs havuzu (en az 2 oyuncu) + Claude (claude-opus-5-5) / Workers AI (@cf/zai-org/glm-5.3-flash)
- `pool-zaab14811` (The Witcher 3): CouchSubs havuzu (en az 2 oyuncu) + Claude (claude-opus-5-5) / Workers AI (@cf/zai-org/glm-5.3-flash)
- `red-dead-redemption-2` (Red Dead Redemption 2): Claude Haiku 5.5 + Claude Opus 5.5, 2026-11-21; ek satırlar: CouchSubs havuzu (en az 2 oyuncu) + Claude Opus 5.5, 2026-11-21 (yeni satırlar: Claude (claude-opus-5-5) / Workers AI (@cf/zai-org/glm-5.3-flash))
  - ek satırlar `pool-rdr-2` paketinden birleştirildi; kaynağı: CouchSubs havuzu (en az 2 oyuncu) + Claude Opus 5.5, 2026-11-21 (yeni satırlar: Claude (claude-opus-5-5) / Workers AI (@cf/zai-org/glm-5.3-flash))

## NOTICE (özgün metin)

```
CouchSubs
Copyright (C) 2026 Sinan Yorulmaz
https://github.com/yorulmazsinan/couchsubs

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU Affero General Public License version 3 (see LICENSE).

If you distribute a modified version or a fork of CouchSubs, the AGPL-3.0
requires you to, among other things:
  - keep this copyright notice and the license notices intact (section 4);
  - carry prominent notices stating that you modified the work and giving a
    relevant date, e.g. "Based on CouchSubs by Sinan Yorulmaz
    (https://github.com/yorulmazsinan/couchsubs), modified on YYYY-MM-DD"
    (section 5a);
  - license the whole work under the AGPL-3.0 and provide its source code
    (sections 5c and 6).
```

## THIRD-PARTY-NOTICES.md, "Game translation packs" bölümü (özgün metin)

## Game translation packs

The packs in `core/Sources/CouchSubsCore/Resources/packs` contain only hashed keys and Turkish text; no game text is
included. The Elden Ring pack (`elden-ring.json.gz`) was translated with Claude (Claude ile çevrildi) from the
English text dumps of the [Carian Archive](https://github.com/AsteriskAmpersand/Carian-Archive) (base game) and
[Impaler's Archive](https://github.com/ividyon/Impalers-Archive) (Shadow of the Erdtree). Its terminology follows the
glossary of the Elden Ring Turkish fan translation by mehmetkrn
([elden-ring-turkce-yama](https://github.com/mehmetkrn/elden-ring-turkce-yama), MIT License, Copyright (c) mehmetkrn).
ELDEN RING is a trademark of FromSoftware, Inc. and BANDAI NAMCO Entertainment Inc.

The Death Stranding Director's Cut pack (`death-stranding-directors-cut.json.gz`) was translated with Claude (Claude ile
çevrildi) from the fan-made English transcript at
[Game Scripts Wiki](https://game-scripts-wiki.blogspot.com/2019/12/death-stranding-full-transcript.html); its terms
follow the Death Stranding 2 pack. DEATH STRANDING is a trademark of Kojima Productions Co., Ltd. / Sony Interactive
Entertainment LLC.

The Marvel's Spider-Man 2 pack (`marvels-spider-man-2.json.gz`) was translated with Claude (Claude ile çevrildi) from
the English [Marvel's Spider-Man 2 script](https://marvels-spider-man.fandom.com/wiki/Marvel%27s_Spider-Man_2_script)
and [menu transcript](https://marvels-spider-man.fandom.com/wiki/Marvel%27s_Spider-Man_2_menu_transcript) on the
Marvel's Spider-Man Wiki (Fandom, text under [CC BY-SA](https://creativecommons.org/licenses/by-sa/3.0/), by its
contributors), and from English lines CouchSubs users read on screen (shared subtitle pool). Marvel's Spider-Man 2 is
a trademark of Marvel and Sony Interactive Entertainment LLC.
