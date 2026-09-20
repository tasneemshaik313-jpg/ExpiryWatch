import re
MONTH_YEAR_4=r"(?<!\d)(0?[1-9]|1[0-2])\s*[/\-.]\s*(20\d{2})(?!\d)"
MONTH_YEAR_2=r"(?<!\d)(0?[1-9]|1[0-2])\s*[/\-.]\s*(2[0-9]|3[0-9])(?!\d)"
DAY_MONTH_YEAR=r"(?<!\d)(0?[1-9]|[12]\d|3[01])\s*[/\-.]\s*(0?[1-9]|1[0-2])\s*[/\-.]\s*(20\d{2})(?!\d)"
def normalize_text(text):
    text=(text or "").upper(); replacements={"M.F.G":"MFG","M.F.D":"MFD","M F G":"MFG","M F D":"MFD","EXP.":"EXP","B.B.E":"BBE","B B E":"BBE","MIG":"MFG","MIG.":"MFG","MIG,":"MFG"}
    for old,new in replacements.items(): text=text.replace(old,new)
    text=re.sub(r"\bGO(?=\s*[-/.]\s*(?:2[0-9]|3[0-9])\b)","09",text); text=re.sub(r"\bG0(?=\s*[-/.]\s*(?:2[0-9]|3[0-9])\b)","09",text); text=re.sub(r"\bC9(?=\s*[-/.]\s*(?:2[0-9]|3[0-9])\b)","09",text); text=re.sub(r"\b(?:UF|OF|G2|G3|G9)(?=\s*[-/.]\s*(?:2[0-9]|3[0-9])\b)","09",text); text=text.replace("¢","7")
    return text
def normalize_month_year(month,year):
    y=str(year); y="20"+y if len(y)==2 else y; return f"{int(month):02d}/{y}"
def all_date_candidates(text):
    out=[]
    for m in re.finditer(DAY_MONTH_YEAR,text): out.append((m.start(),m.end(),f"{int(m.group(2)):02d}/{m.group(3)}","full"))
    for pattern,kind in ((MONTH_YEAR_4,"month_year"),(MONTH_YEAR_2,"month_year")):
        for m in re.finditer(pattern,text):
            value=normalize_month_year(m.group(1),m.group(2))
            if not any(a<=m.start()<b for a,b,*_ in out): out.append((m.start(),m.end(),value,kind))
    return sorted(out,key=lambda x:x[0])
def find_labeled_date(text,labels):
    for line in text.splitlines():
        line=line.strip()
        if line and any(re.search(label,line,re.I) for label in labels):
            candidates=all_date_candidates(line)
            if candidates: return min(candidates,key=lambda c:c[0])[2]
    for label in labels:
        pattern=rf"(?:{label})(?:\s*DATE)?[^0-9]{{0,55}}({MONTH_YEAR_4}|{MONTH_YEAR_2}|{DAY_MONTH_YEAR})"; m=re.search(pattern,text,re.I)
        if m:
            candidates=all_date_candidates(m.group(0))
            if candidates: return candidates[-1][2]
    return None
def extract_shelf_life(text):
    for pattern,multiplier in [(r"\b(\d{1,3})\s*(?:MONTHS?|MOS?)\b",1),(r"\b(\d{1,2})\s*(?:YEARS?|YRS?)\b",12)]:
        m=re.search(pattern,text,re.I)
        if m:
            n=int(m.group(1))*multiplier
            if 1<=n<=120:return n
    return None
def detect_dates(text):
    if not text:return {"expiry_date":None,"manufacturing_date":None,"shelf_life_months":None,"date_source":"none","confidence":0.0,"note":"No text detected."}
    text=normalize_text(text); all_dates=all_date_candidates(text); mfg=find_labeled_date(text,[r"MFG",r"MFD",r"MANUFACTURING",r"MANUFACTURED"]); expiry=find_labeled_date(text,[r"EXPIRY",r"EXPIRATION",r"EXP",r"USE\s*BY",r"BEST\s*BEFORE",r"BBE"]); shelf=extract_shelf_life(text)
    if shelf and re.search(r"FROM\s+(?:THE\s+)?DATE\s+OF\s+MFG|FROM\s+DATE\s+OF\s+MFG",text):
        if not mfg and all_dates:mfg=all_dates[0][2]
        expiry=None
    if expiry==mfg: expiry=None
    if not expiry and mfg and "DATE_SCAN" in text:
        def key(c):
            mm,yy=c[2].split("/"); return (int(yy),int(mm))
        mfg_candidates=[c for c in all_dates if c[2]==mfg]; mfg_key=key(mfg_candidates[0]) if mfg_candidates else (0,0); later=[c for c in all_dates if c[2]!=mfg and key(c)>mfg_key]
        if later: expiry=sorted(later,key=key)[-1][2]
    if expiry:
        source="numeric_label_scan" if "DATE_SCAN" in text and not re.search(r"EXPIRY|EXPIRATION|\bEXP\b|USE\s*BY|BEST\s*BEFORE|\bBBE\b",text) else "printed_expiry"; confidence=.91 if source=="numeric_label_scan" else .97; note=f"Printed expiry detected from the product label: {expiry}."
    elif mfg and shelf: source="mfg_plus_shelf_life"; confidence=.93; note=f"MFG {mfg} + shelf life {shelf} months detected. Expiry is calculated from the package rule."
    elif mfg: source="printed_mfg"; confidence=.82; note=f"Manufacturing date detected: {mfg}."
    else: source="none"; confidence=0.0; note="No clear MFG or expiry date was detected. Try a sharper image."
    return {"expiry_date":expiry,"manufacturing_date":mfg,"shelf_life_months":shelf,"date_source":source,"confidence":confidence,"note":note}
