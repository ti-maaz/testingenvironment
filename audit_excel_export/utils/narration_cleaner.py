import re


_MAX_IDENTIFIER_COUNT = 2
_KNOWN_REPEAT_PHRASES = (
    'CHARGE COLLECTION INCL VAT',
    'OUTWARD REMITTANCE CHARGE',
)
_AMOUNT_TOKEN_RE = re.compile(r'^[+-]?\d+(?:[.,]\d{1,4})?$')
_BANK_REF_RE = re.compile(r'\b(BNK[A-Z0-9]*/\d{4}/\d+)\b', re.IGNORECASE)
_EXPLICIT_REF_RE = re.compile(r'\bREF[:/\-]?\s*([A-Z0-9]+)\b', re.IGNORECASE)
_ODOO_REF_RE = re.compile(
    r'\b([A-Z]{2,})\s+(?:INVOICE|INV)\s*(?:NUMBER|NO|#)?\s*([A-Z0-9-]+)\b',
    re.IGNORECASE,
)
_DASHED_REF_RE = re.compile(r'\b([A-Z]{2,}-[A-Z0-9]+)\b')
_CARD_MASKED_RE = re.compile(r'\b(?:\d{6}[Xx*]{4,}\d{4}|\d{4}[Xx*]{4,}\d{4})\b')
_CARD_FULL_RE = re.compile(r'\b\d{12,19}\b')
_SWIFT_SEGMENT_RE = re.compile(r'/[A-Z0-9]{2,}/?', re.IGNORECASE)

_STRIP_TOKENS = {
    'INWARD',
    'OUTWARD',
    'TT',
    'CHARGE',
    'COLLECTION',
    'INCL',
    'VAT',
    'CREDIT',
    'CARD',
    'PAYMENT',
    'REF',
    'AANI',
    'TO',
    'FROM',
    'TRF',
    'TRANSFER',
    'BENEFRES',
    'BENEF',
    'SWIFT',
}
_UPPERCASE_WORDS = {
    'UAE',
    'VAT',
    'TT',
    'AED',
    'USD',
    'EUR',
}
_LABEL_PART_DELIMITER = ' | '


def _normalize_text(raw_text):
    text = str(raw_text or '')
    text = text.replace('\xa0', ' ')
    text = ' '.join(text.split())
    text = re.sub(r'(?i)\bNUMB\s+ER\b', 'NUMBER', text)
    text = re.sub(r'(?i)\bINCL\.?\s*VAT\b', 'INCL VAT', text)
    text = re.sub(r'(?i)\bT\s*/\s*T\b', 'TT', text)
    # Replace only word-to-word hyphens, preserving ids like PRS-224.
    text = re.sub(r'(?<=[A-Za-z])-(?=[A-Za-z])', ' ', text)
    text = ' '.join(text.split())
    return text


def _collapse_known_repeated_phrases(text):
    collapsed = text
    for phrase in _KNOWN_REPEAT_PHRASES:
        phrase_pattern = r'\s+'.join(map(re.escape, phrase.split()))
        collapsed = re.sub(
            rf'(?i)({phrase_pattern})(?:\s+{phrase_pattern})+',
            r'\1',
            collapsed,
        )
    return collapsed


def _dedupe_adjacent_tokens(tokens, max_window=8):
    out = []
    idx = 0
    token_count = len(tokens)
    while idx < token_count:
        matched_repeat = False
        max_size = min(max_window, (token_count - idx) // 2)
        for size in range(max_size, 0, -1):
            left = tokens[idx:idx + size]
            right = tokens[idx + size:idx + (2 * size)]
            if left == right:
                out.extend(left)
                idx += size * 2
                matched_repeat = True
                break
        if matched_repeat:
            continue

        token = tokens[idx]
        if out and out[-1].upper() == token.upper():
            idx += 1
            continue
        out.append(token)
        idx += 1
    return out


def _extract_bank_ref(text):
    bank_match = _BANK_REF_RE.search(text)
    if bank_match:
        return bank_match.group(1).upper()

    explicit_ref_match = _EXPLICIT_REF_RE.search(text)
    if explicit_ref_match:
        return f"REF:{explicit_ref_match.group(1).upper()}"
    return ''


def _extract_odoo_ref(text):
    match = _ODOO_REF_RE.search(text)
    if match:
        return f"{match.group(1).upper()}-{match.group(2).upper()}"

    dashed_match = _DASHED_REF_RE.search(text)
    if dashed_match:
        return dashed_match.group(1).upper()
    return ''


def _extract_card_last4(text):
    masked_match = _CARD_MASKED_RE.search(text)
    if masked_match:
        digits = ''.join(ch for ch in masked_match.group(0) if ch.isdigit())
        return digits[-4:] if len(digits) >= 4 else ''

    full_match = _CARD_FULL_RE.search(text)
    if full_match:
        return full_match.group(0)[-4:]
    return ''


def _detect_direction(normalized_upper):
    if 'INWARD' in normalized_upper:
        return 'IN'
    if 'OUTWARD' in normalized_upper:
        return 'OUT'
    return ''


def _detect_rail(normalized_upper):
    if any(marker in normalized_upper for marker in ('CREDIT CARD', 'DEBIT CARD', 'CARD PAYMENT')):
        return 'CARD'
    if any(marker in normalized_upper for marker in ('CHARGE', 'FEE', 'COLLECTION')):
        return 'FEE'
    if any(marker in normalized_upper for marker in (' TT ', 'INWARD TT', 'OUTWARD TT', 'REMITTANCE')):
        return 'TT'
    if any(marker in normalized_upper for marker in ('TRANSFER', 'TRF', 'AANI')):
        return 'TRF'
    return ''


def _strip_identifiers_and_noise(text, *, bank_ref, odoo_ref):
    stripped = text
    stripped = _BANK_REF_RE.sub(' ', stripped)
    stripped = _EXPLICIT_REF_RE.sub(' ', stripped)
    stripped = _ODOO_REF_RE.sub(' ', stripped)
    stripped = _CARD_MASKED_RE.sub(' ', stripped)
    stripped = _CARD_FULL_RE.sub(' ', stripped)
    stripped = _SWIFT_SEGMENT_RE.sub(' ', stripped)
    if bank_ref:
        stripped = stripped.replace(bank_ref, ' ')
    if odoo_ref:
        stripped = stripped.replace(odoo_ref, ' ')
    stripped = re.sub(r'[/|]+', ' ', stripped)
    stripped = ' '.join(stripped.split())
    return stripped


def _is_noise_token(token):
    cleaned = token.strip(',:;')
    if not cleaned:
        return True

    upper_cleaned = cleaned.upper()
    if upper_cleaned in _STRIP_TOKENS:
        return True
    if _AMOUNT_TOKEN_RE.match(cleaned):
        return True
    if cleaned.isdigit() and len(cleaned) >= 6:
        return True
    if 'XXXX' in upper_cleaned or '*' in cleaned:
        return True
    return False


def _smart_title(text):
    titled_tokens = []
    for token in text.split():
        stripped = token.strip()
        upper = stripped.upper()
        if upper in _UPPERCASE_WORDS:
            titled_tokens.append(upper)
            continue
        if stripped.isupper() and any(ch.isalpha() for ch in stripped):
            titled_tokens.append(stripped.title())
            continue
        titled_tokens.append(stripped)
    return ' '.join(titled_tokens)


def _safe_truncate(text, max_len):
    if max_len <= 0:
        return ''
    if len(text) <= max_len:
        return text
    cut = text[:max_len - 3].rstrip()
    split_idx = cut.rfind(' ')
    if split_idx >= max(20, max_len // 2):
        cut = cut[:split_idx]
    return cut.rstrip('|• ').rstrip() + '...'


def _unique_parts(parts):
    unique = []
    seen = set()
    for part in parts:
        part = (part or '').strip()
        if not part:
            continue
        marker = part.lower()
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(part)
    return unique


def clean_bank_narration(raw, *, max_len=100):
    normalized = _normalize_text(raw)
    normalized = _collapse_known_repeated_phrases(normalized)
    normalized = ' '.join(_dedupe_adjacent_tokens(normalized.split()))
    normalized_upper = f" {normalized.upper()} "

    bank_ref = _extract_bank_ref(normalized)
    odoo_ref = _extract_odoo_ref(normalized)
    card_last4 = _extract_card_last4(normalized)

    direction = _detect_direction(normalized_upper)
    rail = _detect_rail(normalized_upper)
    has_vat = ' VAT ' in normalized_upper

    stripped = _strip_identifiers_and_noise(normalized, bank_ref=bank_ref, odoo_ref=odoo_ref)
    candidate_tokens = [tok.strip(',:;') for tok in stripped.split() if not _is_noise_token(tok)]
    candidate_tokens = _dedupe_adjacent_tokens(candidate_tokens)
    candidate_text = _smart_title(' '.join(candidate_tokens))

    descriptor = ''
    if re.search(r'(?i)\bRETURN OF DEPOSIT\b', normalized):
        descriptor = 'Return of deposit'
        candidate_text = re.sub(r'(?i)\bRETURN OF DEPOSIT\b', ' ', candidate_text)
        candidate_text = ' '.join(candidate_text.split())

    if rail == 'FEE':
        if 'OUTWARD REMITTANCE' in normalized_upper:
            counterparty = 'Outward remittance'
        elif 'CHARGE COLLECTION' in normalized_upper:
            counterparty = 'Charge collection'
        elif 'CARD' in normalized_upper:
            counterparty = 'Card charge'
        else:
            counterparty = 'Bank charge'
    else:
        counterparty = candidate_text

    identifier_parts = []
    if odoo_ref:
        identifier_parts.append(odoo_ref)
    if bank_ref and bank_ref not in identifier_parts:
        identifier_parts.append(bank_ref)
    identifier_parts = identifier_parts[:_MAX_IDENTIFIER_COUNT]

    if rail == 'CARD':
        clean_parts = ['CARD', 'Payment']
        if card_last4:
            clean_parts.append(f"****{card_last4}")
        clean_parts.extend(identifier_parts)
    elif rail == 'FEE':
        clean_parts = ['FEE', counterparty]
        if has_vat:
            clean_parts.append('VAT')
        clean_parts.extend(identifier_parts)
    elif direction or rail:
        prefix = ' '.join(part for part in (direction, rail) if part).strip()
        clean_parts = [prefix] if prefix else []
        if counterparty:
            clean_parts.append(counterparty)
        if descriptor and descriptor.lower() != counterparty.lower():
            clean_parts.append(descriptor)
        clean_parts.extend(identifier_parts)
    else:
        clean_parts = [counterparty or normalized]
        clean_parts.extend(identifier_parts)

    clean_parts = _unique_parts(clean_parts)
    clean = _safe_truncate(_LABEL_PART_DELIMITER.join(clean_parts), max_len=max_len)

    return {
        'clean': clean or _safe_truncate(normalized, max_len=max_len),
        'direction': direction,
        'rail': rail,
        'counterparty': counterparty,
        'odoo_ref': odoo_ref,
        'bank_ref': bank_ref,
        'card_last4': card_last4,
    }
