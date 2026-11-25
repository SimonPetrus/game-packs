# game-packs

Oyun altyazı çeviri paketleri: oyun başına tek birleşik paket ve `index.json`; her 6 saatte bir kendiliğinden güncellenir.

- Paketler `gh-pages` dalından (GitHub Pages) sunulur: `<taban>/index.json`, `<taban>/<kimlik>.json.gz`.
- Ayrıca `<taban>/v1/packs` (liste) ve `<taban>/v1/packs/<kimlik>` (paket) adresleri aynı içeriği verir.
- Paket biçimi: gzip'li JSON; anahtarlar özetlenmiş satırlar (SHA-256), değerler Türkçe metin. Oyun metni yoktur.
- `index.json`: `{"packs":[{"id","title","version","sha256","size","entries"}]}`; `sha256` indirilen dosyanın özetidir.
- Güncelleme: `.github/workflows/guncelle.yml` kaynaktan yalnız değişen paketleri indirir, `tools/paket_birlestir.py` ile birleştirir;
  değişiklik yoksa yayın yapılmaz. Kaynak alınamazsa ya da sonuç bir önceki yayından belirgin küçükse yayın değişmez.
- Kurulum: depo değişkeni `KAYNAK_ADRES` (kaynak sunucunun taban adresi) tanımlanmalı; Pages kaynağı `gh-pages` dalı olmalı.
- Arapça paketler ayrı ağaçtan sunulur: `<taban>/v1/packs-ar` (liste) ve `<taban>/v1/packs-ar/<kimlik>`; ana liste
  (`v1/packs`, `index.json`) yalnız Türkçe paket içerir. Listedeki her girdide `lang` alanı vardır.
- `ek/`: kaynakta olmayan paketler (paketin `lang` alanı yoksa Türkçe). `katki/`: kaynaktaki aynı kimlikli pakete her
  güncellemede eklenen satırlar (ortakta katkının çevirisi kullanılır); güncellemek için dosya elle değiştirilir.
- Sürüm numarası yalnız paketin içeriği değişince bir artar; önceki yayın okunamazsa güncelleme yayın yapmaz.
- Atıf ve lisans notları: `ATIF.md`.
