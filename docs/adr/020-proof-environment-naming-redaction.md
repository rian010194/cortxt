# ADR-020: Proof environment naming — redact product/partner name from public surface

**Status:** Accepted  \
**Date:** 2026-08-16  \
**Deciders:** Rikard (operatör)  \
**Technical Story:** Repo-publicering (rian010194/cortxt going public); ADR-014/015 namnger internt verktygs-/samarbetsnamnet "Norcom/CSL" som proof environment för Wedge B. Namnet är inte klarlagt för offentlig exponering — det kan bli ett eget internt/lanserat verktyg, ej en tredjeparts kunddata.

## Context

ADR-014 (F0, rad 43) och ADR-015 (F1, rad 20/30/36/37/49) namnger "Norcom/CSL" som proof environment
för wedge B-valideringen (T3). Vid repo-publicering flaggades detta: namnet är sökbart i två godkända
beslutsdokument samt i tre GitHub-issues (#101, #116, #124 — redan redigerade 2026-08-16) och en merged
PR (#100 — hanteras separat).

Beslutsinnehållet i ADR-014/015 (F0-vision, Wedge B-val) är inte ifrågasatt — det är fortfarande korrekt
och Accepted. Enda problemet är att en specifik namngiven identitet syns på en yta som blir publik, innan
ägaren avgjort om namnet ska vara internt eller lanserat.

Per detta repos regel skrivs beslutsdokument (register) aldrig om i efterhand — blir något fel skrivs ett
nytt dokument som supersedes. Detta är inte "beslutet var fel", utan en avgränsad terminologiredaktion:
ADR-014/015 förblir Accepted och normativa för sitt sakinnehåll; endast identifierarens synlighet ändras
framåt.

## Decision

Från och med denna ADR refereras proof environment för wedge B som **"proof environment B"** (kort:
**PE-B**) i alla nya och framtida dokument, issues, och kommunikation — inte det tidigare namnet.

ADR-014 och ADR-015 förblir oredigerade och Accepted för sitt sakbeslut. Vardera filen får en
STATUS-AMENDMENT-notis (samma mönster som ADR-016/017) som pekar hit, så att en läsare som stöter på det
gamla namnet förstår att det ska läsas som "proof environment B" framåt.

Detta dokument, GitHub-issues #101/#116/#124 och PR #100 (om ägaren beslutar) är de enda platser där en
historisk referens till det gamla namnet kvarstår kontrollerat; nya artefakter använder enbart PE-B.

## Consequences

### Positive
- Terminologin är entydig framåt utan att bryta registerregeln (ADR-014/015 orörda).
- Den enda produktnamn-exponeringen som kvarstår är i de två historiska ADR-filerna själva (inte
  issues/PR, som redan redigerats) — en läsare som öppnar just de filerna ser det gamla namnet, men
  README/issue-ytan och all sökbar frontyta gör det inte.

### Negative
- Namnet är fortfarande tekniskt läsbart för den som öppnar `docs/adr/014-*.md` eller
  `docs/adr/015-*.md` direkt, eller `git log`/`git blame`. Detta är inte ett fullständigt scrub — bara
  redigering av filerna på plats (ett medvetet valt alternativ, ej detta) skulle uppnå det, till priset
  av att bryta registerregeln.

### Risks
- Om namnet senare bekräftas vara känsligt på en nivå som kräver fullständig borttagning (t.ex. avtal om
  konfidentialitet), räcker inte denna ADR — då krävs ett explicit beslut att bryta registerregeln för
  just ADR-014/015, eller BFG/git-filter-repo-historikstädning före ev. publicering.

## Alternatives Considered
1. **Redigera ADR-014/015 direkt** — förkastad: bryter registerregeln utan att beslutsinnehållet
   faktiskt var fel.
2. **Lämna namnet synligt i alla dokument** — förkastad: exponerar ett obeslutat produktnamn i publika
   beslutsdokument utan att ägaren tagit ställning.
3. **Terminologi-amendment via ny ADR (vald).**

## Validation
- [x] ADR-014/015 fick STATUS-AMENDMENT-notis som pekar hit.
- [x] docs/adr/README.md uppdaterad med ADR-020.
- [ ] PR #100 hanterad separat (väntar på ägarbeslut).

## Expiry/Review Trigger
- Review by: 2026-11-16
- Trigger: ägaren avgör namnets slutliga offentlighetsstatus (lanserat verktyg vs. permanent internt),
  eller repot flippas till publikt utan att detta beslut är verkställt.
