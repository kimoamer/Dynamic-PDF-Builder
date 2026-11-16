# AI preferences, second dataset

Comparisons of designs by two AI judges, for training the learned selector
(`docs/LEARNED_RANKER_PLAN.md`, M17 and M18). Every row in `ai-preferences.jsonl` says
`reviewer_type: "ai"`, the judge, the date, the method and the prompt hash. There are no human
labels here.

## What was judged

| | |
| --- | --- |
| Documents rendered and judged | 62: the repository's fictional sets (m79, m7, tests) and 14 Wikipedia articles (8 English, 6 Arabic) |
| Designs | 263, up to 5 art directions a document, no design over 12 pages |
| Pairs | 438: every pair of a document's designs |
| Answers | 1,751 of 1,752: each pair in both orders, by two judges |
| How a judge saw a pair | every page as its own image 640 px wide, up to 8 pages a design, labelled A and B only |
| Usable comparisons | 242 of 438 (55%): both judges gave the same answer in both orders, and agreed |
| Same answer in both orders | first judge 345 of 438, second judge 314 of 438 |
| Cost | $23.36 through the Message Batches API |

A pair that flipped when its sides were swapped, or on which the judges differed, is kept in the
file and left out of training. "A" was preferred in 1,026 answers and "B" in 722, so the order of
presentation still matters and both orders stay mandatory.

The plan asked for pages at least 1,000 px wide. 640 px was used to keep the run inside its
budget; body text is about 12 px high at that size.

## The split

`document-split.json` names the families and which are held out. Evaluation is the m7 corpus and
English Wikipedia; training is the m79 corpus, the test documents and Arabic Wikipedia. No family,
author group or picture pool is on both sides, and no picture file is used on both
(`python -m tools.design_learning.corpus describe training/ai_preferences_v2` checks it and
rewrites the split, `provenance.json` and `wikipedia-sources.json`).

The three repository groups were written for this repository and share that origin. Wikipedia text
(CC BY-SA 4.0) and Wikimedia Commons pictures are fetched into `wikipedia-cache/`, which is not
committed; `wikipedia-sources.json` lists each article's title, URL, retrieval date and hash, and
each picture's file page.

## The audit

`owner-delegated-audit.jsonl` holds 24 blind decisions by the session assistant, which is neither
of the judges. The repository owner asked for them in place of a person's. They are AI rows, are
marked `delegated_by_owner`, and are never training labels. They were written from larger sheets
before the judges' answers were collected and before any key was read.

| Compared with the audit (23 clear decisions) | Same answer |
| --- | --- |
| First judge | 17 of 23 |
| Second judge | 14 of 23 |
| Usable comparisons (both judges, both orders) | 11 of 12 |

The preflight (`reference_sampling.audit`) reports ready with two waivers, both the owner's and both
named in its result and in a model's record: this audit in place of 20 human decisions, and no
Word-verified pages (Microsoft Word is not available where this was run).

## Models trained on it

`model-results.json` holds the records. On the 62 held-out comparisons (17 documents):

| Selector | Agrees with the judges | Overrides on 17 documents |
| --- | --- | --- |
| Fixed selector | 56% | |
| Monotone weights | 79% | none it was sure of |
| LightGBM, monotone | 84% | 9: judges preferred its choice 4 times, the fixed choice 2, did not agree 3 |

The booster's gain holds when the documents are resampled (low bound +0.13) and no language got
worse. **Neither model passed its gate, so neither is packaged or can be loaded.** The booster
fails one check: the gate asks for 150 held-out comparisons and there are 62.

## Waiting for judges

Batches `b15` to `b22` hold 36 more English Wikipedia articles, rendered (138 designs) with 336
blind sheets drawn. They are evaluation documents. They were not judged: the API account ran out
of credit. Judging them costs about $10 and should bring the held-out comparisons past 150:

```bash
for b in b15 b16 b17 b18 b19 b20 b21 b22; do
  python -m tools.design_learning --config config/design-learning-v2.json preferences review $b \
    --judge <first judge> --judge <second judge> --page-px 640
done
python -m tools.design_learning --config config/design-learning-v2.json train --name variant-ranker-v2 \
  --provenance training/ai_preferences_v2/provenance.json \
  --delegated-audit training/ai_preferences_v2/owner-delegated-audit.jsonl --pdf-only
```

The articles must be in `wikipedia-cache/` first (`python -m tools.design_learning.corpus fetch
training/ai_preferences_v2/wikipedia-cache`) and rendered again if the renders are gone; a render
whose hash differs from `candidates.jsonl` is refused.

Renders, assets and sheets stay on the machine that made them; `candidates.jsonl` keeps the
SHA-256 of every PDF and DOCX, so a row always says exactly what was judged.
