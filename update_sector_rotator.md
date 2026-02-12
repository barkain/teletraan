# Sector Rotator Prompt Update Summary

## File Modified
`/Users/nadavbarkai/dev/market-analyzer/backend/analysis/agents/sector_rotator.py`

## Changes Made

### 1. Task Section Rewritten (Lines ~332-355)
- Changed "TOP 3 SECTORS to focus on" with "Sector name and ETF symbol" as primary output
- Now reads: "TOP 8-10 SPECIFIC STOCKS AND COMMODITIES across the best-positioned sectors"
- Added instruction: individual stocks are the PRIMARY output, not ETFs
- Added: commodity futures inclusion when macro warrants (GC=F, CL=F, etc.)
- Added: "Every recommendation must be a specific tradeable symbol. Never recommend a sector ETF as a primary position."
- Sector pairs trade updated to use individual stock symbols instead of ETFs

### 2. JSON Example Updated (Lines ~357-410)
- Expanded from 1 top_sectors example to 3, each showing individual stocks
- Energy example: `["XOM", "CVX", "CL=F"]` (includes commodity future)
- Materials example: `["FCX", "NEM", "GC=F"]` (includes gold future)
- sector_pair_trade changed from `"long": "XLK"/"short": "XLU"` to `"long": "NVDA"/"short": "NEE"`
- Added key_observations entry summarizing all individual picks
- Added explicit note: "key_stocks field is REQUIRED for every top_sectors entry"

### 3. Guidelines Section Updated (Lines ~415-425)
- Added: "Individual stock picks are your PRIMARY deliverable"
- Added: "Include commodity futures when macro conditions warrant"
- Added: "Never recommend sector ETFs as positions — they are for analysis context only"
- Updated pairs trade guideline to specify individual stock symbols

### 4. Data Classes — No Changes Needed
- `SectorRecommendation.key_stocks` already exists as `list[str]` with default empty list
- The prompt now enforces that key_stocks is always populated (via prompt instruction)
- No structural changes needed since the field was already present

## Verification
- File compiles successfully: `uv run python -c "import py_compile; py_compile.compile('analysis/agents/sector_rotator.py', doraise=True)"`
