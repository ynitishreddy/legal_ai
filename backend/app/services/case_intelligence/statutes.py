import re
from typing import Dict, Any, Optional

class StatuteNormalizer:
    # Common statute abbreviation lookup map
    ACT_ALIASES = {
        "ipc": "Indian Penal Code",
        "indian penal code": "Indian Penal Code",
        "crpc": "Code of Criminal Procedure",
        "code of criminal procedure": "Code of Criminal Procedure",
        "cpc": "Code of Civil Procedure",
        "code of civil procedure": "Code of Civil Procedure",
        "constitution": "Constitution of India",
        "constitution of india": "Constitution of India",
        "ndps": "Narcotic Drugs and Psychotropic Substances Act",
        "ndps act": "Narcotic Drugs and Psychotropic Substances Act"
    }

    # Common Offence Categories based on Indian Penal Code sections
    OFFENCE_CATEGORIES = {
        "302": "Murder / Homicide",
        "307": "Attempt to Murder",
        "376": "Sexual Offences / Rape",
        "379": "Theft / Larceny",
        "420": "Cheating and Dishonesty",
        "498a": "Cruelty by Husband or Relatives",
        "120b": "Criminal Conspiracy",
        "149": "Unlawful Assembly"
    }

    @classmethod
    def normalize(cls, raw_act: str, raw_section: Optional[str] = None) -> Dict[str, Any]:
        """
        Translates raw statutory inputs (e.g. 'IPC', '302') into clean canonical names,
        offence categories, and normalized references.
        """
        canonical_act = cls.ACT_ALIASES.get(raw_act.strip().lower(), raw_act.strip())
        
        sec = raw_section.strip() if raw_section else ""
        # Remove common Section prefixes from section ref
        sec_num = re.sub(r"^(?:Sec\.|Section|Sec)\s*", "", sec, flags=re.IGNORECASE).strip()

        # Resolve offence category
        offence_category = "Other Legal Infractions"
        if canonical_act == "Indian Penal Code":
            offence_category = cls.OFFENCE_CATEGORIES.get(sec_num, "General IPC Offence")

        normalized_ref = f"{canonical_act}"
        if sec_num:
            normalized_ref = f"{canonical_act}, Section {sec_num}"

        return {
            "canonical_act": canonical_act,
            "section_number": sec_num or None,
            "normalized_reference": normalized_ref,
            "offence_category": offence_category,
            "aliases": f"{raw_act}, {raw_act.upper()}"
        }
