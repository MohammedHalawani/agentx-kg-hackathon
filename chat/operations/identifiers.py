"""Reversible public identifiers over the frozen, audited V2 storage namespace.

No records, historical receipts, hashes or signed cursors are rewritten. This
boundary allows a later shadow migration without losing operational history.
"""
import re

def storage_value(value):
    if isinstance(value,str) and value.startswith("SYN-"):return "DEMO-"+value[4:]
    if isinstance(value,list):return [storage_value(v) for v in value]
    if isinstance(value,tuple):return tuple(storage_value(v) for v in value)
    if isinstance(value,dict):return {k:v if k in ("cursor","idempotency_key") else storage_value(v) for k,v in value.items()}
    return value

def public_value(value):
    if isinstance(value,str):
        value=value.replace("DEMO-","SYN-").replace("SYNTHETIC_DEMO_ASSUMPTION","SYNTHETIC_ASSUMPTION")
        value=re.sub(r"\bdemo\b","synthetic",value,flags=re.I)
        value=re.sub(r"\bfixture\b","generated",value,flags=re.I)
        return value.replace("local_demo","local_synthetic").replace("_DEMO_","_SYNTHETIC_").replace("_fixture","_scenario").replace("_FIXTURE","_SCENARIO")
    if isinstance(value,list):return [public_value(v) for v in value]
    if isinstance(value,tuple):return tuple(public_value(v) for v in value)
    if isinstance(value,dict):return {k:v if k in ("token","next_cursor","previous_cursor") else public_value(v) for k,v in value.items() if k!="demo"}
    return value
