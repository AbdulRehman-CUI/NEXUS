# Reproducible Phase 2 retrieval evaluation

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_retrieval.py --embedding-provider onnx
.\.venv\Scripts\python.exe scripts/evaluate_retrieval.py --embedding-provider hash --output artifacts/retrieval-evaluation-hash.json
```

The first ONNX run downloads only the public pinned MiniLM tokenizer and quantized model (~23 MB). No generative provider, account, key, paid service or GPU is used. Reuse the output data directory for repeat runs; it contains a dedicated synthetic evaluation workspace. To share the application's model cache, set `NEXUS_MODEL_CACHE_DIR=data/models` in the process environment. `HF_HUB_OFFLINE=1` prevents network after caching. Optional PyTorch comparison: select `sentence-transformers` after installing the optional ML profile.

## Corpus and labels

`examples/evaluation/` contains a two-page PDF and ten synthetic vault notes. Twelve questions cover exact terms/phrases, paraphrases, a two-source question, dates/ownership, adversarial instructions and two unsupported questions. The vault also contains ambiguous basenames, missing notes/attachments and unsafe links. No private user content is used.

`questions.json` checks in relevance labels as stable source-span SHA-256 IDs over canonical JSON `{path,page,heading,text}`. The command verifies every label against actual extracted spans, then records the mapping to the run-specific SQL document/version/span/chunk IDs in the result JSON. A stale label fails the run instead of silently changing relevance. All returned source URLs are opened and excerpts checked against stored passages.

Recall@k is the fraction of a case's relevant source spans retrieved in its top-k chunks (deduplicated to spans). MRR is the reciprocal rank of the first relevant span. Averages use the **ten answerable cases**. Unsupported cases are reported separately as cases with any retrieval hit; they do not inflate recall/MRR denominators. Multi-source recall requires both labeled spans. The baseline is the dense-only strategy under the same current candidate/context assembly, not a separately executed historical Git checkout.

## Actual measured runs — 4 November 2026

Same corpus, k=3, candidate count=15, no query rewriting, no reranker, same filters and context assembly per run:

| Embedding / strategy | Recall@3 | MRR |
| --- | ---: | ---: |
| Hash / dense strategy | 0.9500 | 0.9000 |
| Hash / keyword | 1.0000 | 0.9500 |
| Hash / hybrid | 1.0000 | 0.9500 |
| Quantized MiniLM ONNX / semantic | 1.0000 | 0.9500 |
| Quantized MiniLM ONNX / keyword | 1.0000 | 0.9500 |
| Quantized MiniLM ONNX / hybrid | 1.0000 | 0.9500 |

Hash run total: **4.136 seconds**. ONNX run total: **4.901 seconds**, using already downloaded model files. Timings include ingestion/startup/evaluation and are a single observation, not a performance benchmark median. The JSON records per-strategy time, case results, actual source mapping and host information. Host: Windows 11 build 26200, AMD64, Intel64 Family 6 Model 140 Stepping 1, Python 3.12.14; ONNX CPUExecutionProvider, two inference threads, batch eight. No GPU was used.

**No general hybrid improvement is claimed.** Keyword and hybrid tie on this small corpus; real MiniLM dense retrieval also ties. Hash results measure vector plumbing, not semantic quality. **Both unsupported questions returned candidates in all six measured configurations.** A permissive distance/term gate is not an abstention classifier. Retrieval hits do not prove that evidence answers a question, and source identity does not prove generated-claim entailment. The adversarial retrieval case does not establish a model's resistance to every prompt injection.

Checked-in run details: `docs/retrieval-evaluation-hash.json` and `docs/retrieval-evaluation-onnx.json`. These contain only synthetic source identities, case results and measured host/run information.

## Regression and semantic checks

```powershell
# No model downloads in the default tests:
.\.venv\Scripts\python.exe -m pytest apps/api -q
# Real cached ONNX paraphrase test:
$env:NEXUS_TEST_ONNX='1'
$env:NEXUS_MODEL_CACHE_DIR='data/models'
.\.venv\Scripts\python.exe -m pytest apps/api -q
```

The optional PyTorch/MiniLM test uses `NEXUS_TEST_SEMANTIC=1`. It was skipped on this host because that optional runtime could not be installed within the earlier disk limit. ONNX semantic extraction/retrieval **was** run successfully, including a no-shared-keyword vacation/annual-leave paraphrase. Full cross-encoder execution and live cloud generation remain separate optional checks. See `PHASE_2_REPORT.md` for final exact counts and browser results.
