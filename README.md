# Handpicked

![Handpicked: three diamonds on the same hand at their listed sizes, with the measured finger and the board](docs/img/hero.jpg)

[![ci](https://github.com/Marc-Dvci/handpicked/actions/workflows/ci.yml/badge.svg)](https://github.com/Marc-Dvci/handpicked/actions/workflows/ci.yml)
![finger width](https://img.shields.io/badge/finger%20width-median%200.05%20mm%20held--out-1d46c4)
![try-on size](https://img.shields.io/badge/stone%20size%20on%20the%20hand-193%2F197%20renders%20within%205%25-1d46c4)
![listing reader](https://img.shields.io/badge/listing%20reader-98%25%20fields%2C%200%20wrong%20numbers-1d46c4)
![tests](https://img.shields.io/badge/tests-116%20%2B%207%20in%20the%20browser-15171c)
![axe-core](https://img.shields.io/badge/axe--core-0%20violations-15171c)
![licence](https://img.shields.io/badge/licence-MIT-15171c)

**Handpicked shows a diamond shopper which of the stones they are comparing will look biggest on their own hand, and what each face-up square millimetre costs.**

Someone close to me paid the one-carat premium for a stone that looked like the 0.9.

| | |
|---|---|
| Track | eCommerce VTO |
| YouCam API | Ring Virtual Try-On (`/s2s/v2.0/task/2d-vto/ring`), called live: 228 calls, median 4.6 s |
| Built with | YouCam Ring Virtual Try-On API, Alibaba Cloud Model Studio, Python, FastAPI, OpenCV, MediaPipe, React, Blender |
| Headline | Each stone is drawn on the shopper's photo at its listed width: 193 of 197 live renders within 5% on hands the calibration did not see |
| Try it without keys | `docker build -t handpicked . && docker run -p 8080:8080 handpicked`, then open http://localhost:8080 ([quickstart](#quickstart)) |

## For judges

| Criterion | Where it is answered |
|---|---|
| Technological implementation | [How the YouCam API is used](#how-the-youcam-api-is-used), `handpicked/youcam.py`, `handpicked/service.py`, `handpicked/library.py`, evidence [E3](#evidence) (204 live calls) |
| Design | [See it work](#see-it-work), `web/src`, browser tests with axe-core in `web/e2e/app.spec.ts` (0 violations on 6 page states, phone layout included) |
| Potential impact | [The problem](#the-problem-and-who-it-is-for), evidence [E5](#evidence), the jeweller view (`#/jewellers`, `handpicked/merchant.py`) |
| Quality of the idea | [How it works](#how-it-works): a size-true try-on needs a ring image whose proportions match the shopper's finger, so the product picks one of 432 dimension-exact renders per request and measures the result |
| Claims and the code behind them | [Claims table](#claims-table) |

## See it work

1. **Your hand.** Pick a sample hand or upload a photo of the back of your hand on a sheet of A4 paper. The finger is measured where the ring sits.

   ![The measurement: the sheet with its known sides, the finger at the ring position with its width, and the facts table](docs/img/measure.jpg)

2. **The stones you are comparing.** Paste two to four listings. Every value is shown with the words it was read from.

   ![Three listings with each value highlighted where it was read](docs/img/readings.png)

3. **On paper.** Face-up area, share of the finger covered, price per face-up mm², spread against a typical cut, and the weight the millimetres imply. One verdict sentence from the computed facts.

   ![The board: the 0.92 ct oval ranks first at $70 per mm²; the verdict below](docs/img/board.png)

4. **On your hand.** Each stone drawn on the photo by the YouCam Ring Virtual Try-On at its listed width, with the size check under each render.

   ![The bare finger and the three stones on it, each with its render check](docs/img/tryon-cards.jpg)

5. **Your decision.** One stone, the ring size, the reason, and the facts; print it or copy it to the seller.

A listing without millimetres waits outside the ranking with a question for the seller, and an instruction pasted into a listing is struck out and never read:

<img src="docs/img/waiting.png" alt="A listing with an injected instruction struck out and a question for the seller" width="360">

## The problem and who it is for

Carat is weight. What a person sees on a hand is the stone's face-up area against the finger, and shoppers compare stones by carat and price. Natural rounds cost 23.9% more per carat once they reach 1.00 ct (median over the 74 colour and clarity cells PriceScope prices in both the 0.90-0.99 and 1.00-1.19 ct bands, October 2026), while a 0.93 ct round and a 1.01 ct round differ by 0.12 mm across a 16.7 mm finger. Perfect Corp's own diamond size chart shows the same scale: a 1 ct round covers 39% of a size 6 finger.

The person is an engagement-ring shopper with two to four browser tabs open on stones from different sellers, deciding whether the heavier stone is worth the extra money. They have a phone, a sheet of paper and their own hand. Handpicked answers on that hand, in millimetres and money, before they buy.

The second user is the jeweller: the same measurement ranks a stock feed for the customer in front of them, and one script tag puts a "Compare on your hand" button on a product page.

## How it works

![Architecture: code computes every number and check; the YouCam Ring VTO draws the stone; the model on Model Studio only reads gaps in listing text and rewords the verdict](docs/img/architecture.svg)

**The boundary.** Numbers, rankings, sizes and the render audit come from code. The model on Alibaba Cloud Model Studio reads only the listing fields the rules left empty and rewords the verdict; each value it returns is kept only if its quote is in the listing and states that value, and its sentence is shown only if it keeps every number of the template and adds none. Photos never reach the model.

- **Finger metrology** (`handpicked/metrology.py`). The sheet's four corners give the scale and the camera's position. MediaPipe finds the ring finger; its edges are read where the colour falls fastest across the finger, at seven positions where a ring sits. The silhouette a camera sees is wider than the finger by an amount that depends on where the camera was, so the width is solved from the camera pose (parallax correction). A photo that fails a capture check (tilt over 35°, under 2.5 px per mm, edges that disagree) is refused with an instruction.
- **Ring size** (`handpicked/fit.py`). Inner diameter equal to the finger width, as in Perfect Corp's size chart; US, EU and UK sizes from ISO 8653; a wide knuckle moves the size up.
- **Listing reader** (`handpicked/listing.py`). Rules read carat, shape, measurements, price, lab, origin, colour and clarity in English and French formats, with the character span of each value. Instruction-like text is masked before anything reads it. Moissanite, simulants and unsupported shapes wait outside the board. "From" prices, instalments and setting prices are not read as the stone's price.
- **Board** (`handpicked/compare.py`, `handpicked/gems.py`). Face-up area from the outline of each shape, coverage of the measured finger, price per mm², spread against a typical stone of the same weight (Perfect Corp's size chart), the weight the millimetres imply, look-alike pairs (same shape, within 0.2 mm, more than 10% apart in price), and the round-weight price step for natural stones.
- **Size-true try-on** (`handpicked/library.py`, `handpicked/service.py`, `handpicked/audit.py`). See below.

## How the YouCam API is used

| YouCam product | Call | Why it is needed |
|---|---|---|
| Ring Virtual Try-On | File API upload of the hand crop and of one ring render, `POST /s2s/v2.0/task/2d-vto/ring` with `ring_wearing_finger`, `ring_wearing_location` from the measurement and `ring_anchor_point` from the render, then polling | The shopper must see each stone on their own finger, with their own skin and light, at the stone's real size. A drawing to scale shows the numbers; the try-on shows what the hand will look like |

The engine maps the ring's anchor points (the band's inner edge) to the finger, so it draws the band about 1.15 times the finger width and the stone follows the band. A product photo used for every weight is therefore wrong by up to 67% (E3). Handpicked ships 432 Blender renders: 8 shapes, 2 metals, stone-to-band ratios from 0.16 to 0.68 in steps of 0.02. For a stone of width *w* on a finger of width *f*, it picks the render whose ratio equals *w* / *f* / (c_shape × band fit), and scales the anchor points by at most 6% for the rest. c_shape and the band fit of each sample hand were measured on 204 live calls with flat green calibration stones (`eval/e3_render_scale.py`).

Every render that comes back is measured before it is shown: the band's width across the finger is read from the pixels the try-on changed, and the stone's drawn width follows from it. A render more than 5% off is re-rendered once with the band fit that render showed. Each try-on card states the result.

Live calls go through a unit ledger (`var/units.jsonl`): a cap per day, a cap per browser session, and a floor on the account's remaining units below which live calls stop. Without a key, the server answers from 18 recorded renders of the sample hands (`assets/tryon`), all within 3.1% of their target.

## What it will not do

- It does not send a photo to a language model, and it re-encodes uploads without EXIF (location, device). Uploads are deleted after 24 hours.
- It does not rank a stone whose millimetres are missing; it drafts the question to the seller instead.
- It does not compare moissanite, simulants or shapes outside its eight.
- It does not obey text inside a listing; instruction-like text is struck out.
- It does not show a model sentence that adds a number; the rules' sentence is shown.
- It does not measure a photo that fails a capture check; it says what to change.
- It does not upload a photo until the visitor confirms the hand is theirs or its owner agreed.

## Evidence

Every figure comes from a file in `eval/results`, written by the command next to it. Test sets were committed before the code they score; held-out halves were run once.

| Set | Result | Command |
|---|---|---|
| **E1** finger width, rendered scenes of known size (`tools/render_bench.py`), held-out bench | 39 of 40 measured (1 refused: finger edges unclear); median error 0.05 mm, 90th percentile 0.10 mm, largest 0.42 mm; without EXIF focal length, median 0.04 mm. Before: the first method had a median of 0.43 mm and a 90th percentile of 1.26 mm; without the parallax correction the held-out median is 0.42 mm | `python eval/e1_metrology.py --bench <dir> --tag heldout` |
| **E2** same hand, 12 more captures each (re-encoded, rescaled, rotated, re-lit, blurred, noisy) | 81 of 84 measured; median change 0.10 mm, 90th percentile 0.36 mm, largest 0.68 mm; ring size within half a size in 79 of 81. Before: 75 of 84 measured, and a darker photo whose sheet corner was misread came out 8.62 mm narrower without a refusal; failed capture checks now refuse the photo | `python eval/e2_robustness.py` |
| **E3** stone size on the hand, 204 live Ring VTO calls on the sample hands, 8 shapes | 0 failed, median 4.6 s. Stone width read through the band, with c_shape fitted on the other hands: median error 1.11%, 90th percentile 3.25%, 193 of 197 within 5%. With every hand in the fit: median 0.95%, 197 of 197 within 5%. One store photo for every size: up to 67% off. 7 renders excluded where the stone hides the band | `python eval/e3_render_scale.py` |
| **E4** listing reader, 60 listings in 6 formats (EN, FR), held-out half | 98.0% of 300 fields correct, 0 wrong numbers on the board, 3 of 3 injected instructions ignored, 0 values without a quote. Before: the first model run re-introduced 2 wrong prices (a "from" price and a setting price); the model's quotes now pass the same price rules. Ten free-text listings: rules alone 77% of fields and 0 stones on the board; with the model 85% and 7 of 10, 0 wrong numbers | `python eval/e4_listing_reader.py --split heldout --model` |
| **E5** shortlists priced from PriceScope cells, October 2026 | 144 shortlists (a round at 0.70, 1.00, 1.50 or 2.00 ct, a round just under the weight, and an oval, pear, radiant or princess just under it, 9 grades): in 36, a cheaper stone faces up at least as large as the heaviest (every one an oval), median saving $3,345 (46.9%). In all 144, the round just under the weight is a median 0.16 mm narrower across the finger and $2,690 cheaper | `python eval/e5_decision_value.py` |
| Tests | 116 Python tests (metrology, listing reader, board, audit, service, API, spending caps, the model boundary); 7 browser tests drive every screen and button with axe-core (0 violations) | `python -m pytest -q` and `cd web && npx playwright test` |

**Real and synthetic:** every YouCam render and every Model Studio call is real; prices are PriceScope's published averages; the seven hands are generated images of no real person (Qwen-Image, `tools/gen_hands.py`), the ring images and the E1 scenes are Blender renders, and the 70 listings were written for the evaluation.

## Quickstart

Without any key the server runs in replay mode: measurement, the listing rules, the board and the jeweller view run live; try-ons play the 18 recorded renders of sample hands 1, 2 and 5 with the sample shortlist; the verdict is the rules' sentence.

```bash
git clone https://github.com/Marc-Dvci/handpicked && cd handpicked
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
(cd web && npm ci && npm run build)
uvicorn handpicked.app:app --port 8000                 # open http://localhost:8000
```

Live mode reads these variables (or `KEY=value` files listed in `HANDPICKED_ENV_FILE`):

| Variable | Default | Meaning |
|---|---|---|
| `YOUCAM_API_KEY` | unset | Live Ring VTO calls |
| `DASHSCOPE_API_KEY` | unset | Model Studio for the listing gaps and the verdict wording |
| `HANDPICKED_DAY_UNITS` / `HANDPICKED_SESSION_UNITS` | 120 / 8 | YouCam units per day and per browser session |
| `HANDPICKED_UNIT_FLOOR` | 0 | Live try-ons stop before the account drops below this many units |
| `HANDPICKED_DAY_TOKENS` | 60000 | Model tokens per day |

Deployment: `deploy/service.yaml` (Cloud Run, at most 2 instances, billed per request) and `deploy/deploy.sh` (image build, secrets in Secret Manager, a keep-warm ping, a budget alert on gross spend).

## Layout

```
handpicked/     metrology, fit, listing reader, board, ring library, audit, YouCam and Model Studio clients, API
web/            React app (src), browser tests with axe-core (e2e), capture script (scripts)
assets/         sample hands, 432 ring renders, calibration, recorded try-ons, jeweller feed, hand landmark model
eval/           E1-E5 scripts, listing corpus, PriceScope cells, results
tools/          Blender renderers (rings, bench), hand generator, packers, recorder
tests/          unit, service, API and boundary tests
docs/           METHOD.md, images
deploy/         Cloud Run service and deploy script
```

Method and sources: [`docs/METHOD.md`](docs/METHOD.md). Licence: [MIT](LICENSE).

## Claims table

| Claim | Code | Test or evidence |
|---|---|---|
| Finger width from one photo, corrected for where the camera was | `metrology.py` (`camera_pose`, `solve_width`) | `tests/test_metrology.py::test_parallax_correction_shrinks_the_silhouette_width`, E1 |
| A photo failing a capture check is refused | `metrology.py` (`CHECK_REFUSALS`) | `test_photo_below_the_resolution_floor_is_refused`, E2 |
| A finger touching its neighbour is refused | `metrology.py` (`_ring_window`) | `test_finger_touching_its_neighbour_is_refused` |
| A sheet on a light grey table is still found | `metrology.py` (`find_sheet`) | `test_sheet_on_a_light_grey_table_is_still_found` |
| Ring size by ISO 8653, knuckle rule | `fit.py` | `tests/test_fit.py` |
| Every listing value carries its source span | `listing.py` | `test_spans_point_at_the_source` |
| Injected instructions are masked | `listing.py` | `test_injected_instruction_is_not_read`, `test_french_injection_is_masked`, `tests/test_app.py::test_injected_instruction_is_masked_on_the_board`, E4 |
| A model value is kept only if its quote states it | `listing.ground_model_fields` | `test_model_value_must_match_its_quote`, `test_model_cannot_invent_a_number` |
| "From", instalment and setting prices are not the stone's price | `listing.py` (`price_context`) | `test_financing_and_setting_prices_are_skipped`, `test_model_cannot_bring_back_a_from_price` |
| Non-diamonds wait outside the board | `compare.stone_from_listing` | `test_non_diamond_waits_outside_the_ranking`, `test_moissanite_waits_outside_the_board` |
| Ranked by price per face-up mm² | `compare.board` | `test_board_ranks_by_price_per_face_up_mm2` |
| Look-alike stones are named with their price gap | `compare.look_alike` | `test_look_alike_rounds_are_named_with_their_price_gap` |
| Two listings of one stone get no winner | `compare.verdict_facts` | `test_identical_stones_give_identical_verdict_and_no_winner`, `test_same_stone_twice_makes_no_ranking_claim` |
| A model sentence with a new number is replaced | `service.verdict`, `llm.numbers_grounded` | `test_verdict_with_an_invented_number_is_refused`, `tests/test_boundary.py::test_model_sentence_with_a_new_number_is_replaced_by_the_rules` |
| Photos never reach the model | `service.py`, `llm.py` | `tests/test_boundary.py::test_photos_never_reach_the_model` |
| Uploads are stored without EXIF | `hands.normalise` | `tests/test_boundary.py::test_upload_is_stored_without_exif` |
| The render is chosen for the target size | `library.choose` | `tests/test_compare.py::test_library_choice_hits_the_target_ratio`, E3 |
| Every render is measured; off by more than 5% is re-rendered once | `audit.py`, `service.tryon` | `tests/test_audit.py`, `tests/test_service.py::test_off_render_is_re_rendered_once_with_a_smaller_ring` |
| Unit caps per day and session, credit floor | `youcam.Ledger`, `youcam.YouCam` | `tests/test_youcam.py` |
| Replay mode needs no key | `youcam.YouCam.cached` | `tests/test_app.py::test_recorded_try_on_replays_with_its_audit`, `tests/test_youcam.py::test_recorded_result_needs_no_key_and_no_budget` |
| Jeweller ranking: largest on the finger within budget | `merchant.rank` | `tests/test_app.py::test_jeweller_ranking_is_largest_first_within_budget` |
| Every screen and button works; accessibility | `web/src` | `web/e2e/app.spec.ts` (axe-core, 0 violations) |
