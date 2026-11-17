import unicodedata

def is_rtl(text: str) -> bool:
    """Detect if a text contains predominantly Arabic/Hebrew (RTL) characters."""
    rtl_count = 0
    total_alpha = 0
    for char in text:
        if char.isalpha():
            total_alpha += 1
            if unicodedata.bidirectional(char) in ('R', 'AL'):
                rtl_count += 1
    
    # Threshold for treating the block as right-to-left
    if total_alpha > 0 and (rtl_count / total_alpha) > 0.4:
        return True
    return False

def apply_rtl_reshaping(text: str) -> str:
    """If needed, apply complex text layout (CTL) shaping for Arabic strings."""
    # Note: ReportLab 4.x has some native bidi handling when paragraph direction is 'RTL'
    # But for full correctness across all environments, python-bidi and arabic-reshaper are used.
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        reshaped_text = arabic_reshaper.reshape(text)
        bidi_text = get_display(reshaped_text)
        return bidi_text
    except ImportError:
        # Fallback to pure string if packages are missing
        return text
