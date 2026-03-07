# ML Suggester — Multi-Currency Data Transformer

Transforms Excel ledger blocks (variable posting rows + total row) into a **long, line-level dataset**:
- **Input columns** (example):  
  `Date`, `Affected Accounts`, `Transaction Description`,  
  `Debited Amount KRW`, `Credited Amount KRW`,  
  `Debited Amount MYR`, `Credited Amount MYR`,  
  `Debited Amount CNY`, `Credited Amount CNY`
- Automatically detects any number of currencies from header suffixes.

## Install
```bash
pip install -e .
