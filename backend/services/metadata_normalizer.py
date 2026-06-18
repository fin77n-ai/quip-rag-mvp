import re

def normalize_metadata(doc_title: str, sheet_name: str) -> tuple[str, str, str]:
    """
    Returns (sprint, language, video_code)
    """
    sprint = ""
    language = ""
    video_code = ""

    doc_title = (doc_title or "").strip()
    sheet_name = (sheet_name or "").strip()

    # Detect sprint from doc_title (e.g. MS10, MS11)
    sprint_match = re.search(r'(MS\d+|Sprint\s*\d+)', doc_title, re.IGNORECASE)
    if sprint_match:
        sprint = sprint_match.group(1).upper()

    # DETECT LANGUAGE
    lang_pattern = re.compile(r'^(ZHCN|JAJP|ESMX|PTBR|FRFR|DEDE|FRCA|ENGB|ESLA|GLOBAL)$', re.IGNORECASE)
    if lang_pattern.match(sheet_name):
        language = sheet_name.upper()
    else:
        # Check if language is in the doc title (Old structure, e.g. MS10_JP_Issue Log)
        lang_match = re.search(r'_(JAJP|JP|CN|FR|DE|ES|PT|BR|LA)_', doc_title, re.IGNORECASE)
        if lang_match:
            language = lang_match.group(1).upper()
            if language == 'JP': language = 'JAJP'
            if language == 'CN': language = 'ZHCN'

    # DETECT VIDEO CODE
    video_pattern = re.compile(r'([A-Z]{2,3}\d{3,4})', re.IGNORECASE)

    # Try doc title first (e.g. TW2575_How_to_leave...)
    video_match = video_pattern.search(doc_title)
    if video_match:
        video_code = video_match.group(1).upper()
    else:
        # Try sheet name (e.g. YT801_Five_helpful...)
        video_match = video_pattern.search(sheet_name)
        if video_match:
            video_code = video_match.group(1).upper()

    return sprint, language, video_code

if __name__ == "__main__":
    cases = [
        ("DEMO101_Reset_account_password", "ZHCN"),
        ("TW2575_How_to_leave_a_video_message_in_Facetime_Issue Log", "GLOBAL"),
        ("TW2575_How_to_leave_a_video_message_in_Facetime_Issue Log", "PTBR"),
        ("MS10_JP_Issue Log", "YT801_Five_helpful_AirPods_tips"),
        ("MS10_JP_Issue Log", "TW2673_How_to_turn_iPhone_off_or_on"),
    ]
    for doc_title, sheet in cases:
        print(f"[{doc_title}] + [{sheet}] =>", normalize_metadata(doc_title, sheet))
