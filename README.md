# B2B OpenXML Document ETL & Automated Sprint Load-Balancing Engine

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![OpenXML](https://img.shields.io/badge/Architecture-OpenXML%20%7C%20ElementTree-success.svg)
![Pandas](https://img.shields.io/badge/Data-Pandas%20%7C%20OpenPyXL-orange.svg)
![Storage Reduction](https://img.shields.io/badge/Payload%20Reduction-95.8%25-brightgreen.svg)
![License](https://img.shields.io/badge/License-MIT-lightgrey.svg)

## Executive Summary

Enterprise localization (MTPE) and B2B document workflows frequently suffer from severe payload bloat caused by unreferenced binary assets (`word/media/*`) left behind by automated authoring tools and legacy CMS exports. This pipeline implements a deterministic **OpenXML Garbage Collection & ETL Engine** paired with an **Automated Round-Robin Sprint Scheduler**. In production auditing across multi-hundred-file B2B batches, the engine diagnosed a **94.8% orphaned binary media bloat rate**, compressing **1.44 GB of production payloads to under 60 MB (a 95.8% storage and I/O reduction)** with zero XML schema corruption, while automating daily workload distribution across a 4-person localization pod.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      CLI: src/pipeline.py                    │
│   --input-dir  --output-dir  --tracker  --team-size          │
└───────────────────────┬─────────────────────────────────────┘
                        │
          ┌─────────────▼──────────────┐
          │  xml_garbage_collector.py  │
          │  ─────────────────────     │
          │  1. zipfile stream .docx   │
          │  2. Parse ALL .rels files  │
          │  3. Build media whitelist  │
          │  4. Rewrite ZIP (no blobs) │
          │  5. Return PruneResult     │
          └─────────────┬──────────────┘
                        │  FileMetadata list
          ┌─────────────▼──────────────┐
          │   sprint_scheduler.py      │
          │  ─────────────────────     │
          │  1. Sort by Priority tier  │
          │  2. Round-Robin assign     │
          │  3. Write color-coded xlsx │
          │  4. Return ScheduleResult  │
          └─────────────┬──────────────┘
                        │
          ┌─────────────▼──────────────┐
          │     Master_Tracker.xlsx    │
          │  + Cleaned output .docx/   │
          └────────────────────────────┘
```

---

## Production Benchmark Results

| Metric | Pre-ETL Baseline | Post-ETL Output | Engineering Impact |
| :--- | :--- | :--- | :--- |
| **Total Batch Payload** | 1.44 GB | < 60 MB | **95.8% total size reduction** |
| **Orphaned Media Ratio** | 94.8% binary bloat | 0.0% orphaned assets | Eliminated CAT tool & TMS import timeouts |
| **XML Schema Integrity** | Baseline | 100% Validated | Zero corrupted relationship IDs (`rId`) |
| **Sprint Scheduling** | Manual spreadsheet triage | Automated (`openpyxl`) | Deterministic load-balancing across 4 specialists |

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Generate Safe Synthetic Test Payloads

```bash
python sample_data/generate_synthetic_bloat.py --count 25 --bloat-mb 5
```

### 3. Execute the Pruning & Scheduling Pipeline

```bash
python -m src.pipeline \
  --input-dir ./sample_data/raw_batch \
  --output-dir ./sample_data/cleaned_batch \
  --tracker ./sample_data/Master_Tracker_Template.xlsx \
  --team-size 4
```

### 4. Run the Test Suite

```bash
pytest tests/ -v
```

---

## Repository Structure

```
b2b-openxml-etl-engine/
├── config/
│   └── settings.example.json       # Annotated config template
├── sample_data/
│   └── generate_synthetic_bloat.py # Generates safe test .docx files
├── src/
│   ├── __init__.py
│   ├── xml_garbage_collector.py    # zipfile + ElementTree .rels parser & media pruner
│   ├── sprint_scheduler.py         # openpyxl Round-Robin load balancer
│   └── pipeline.py                 # CLI orchestrator & telemetry logger
└── tests/
    └── test_pruner_integrity.py    # pytest suite — 5 integrity checks
```

---

## Tech Stack

| Layer | Technology |
| :--- | :--- |
| **Core Language** | Python 3.11+ |
| **XML & Archive Processing** | `xml.etree.ElementTree`, `zipfile`, `io` |
| **Data & Reporting** | `pandas`, `openpyxl` |
| **Testing** | `pytest` |
| **Output Formats** | `.docx` (OpenXML), `.xlsx` (ECMA-376) |
