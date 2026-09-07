// Mock payloads shaped exactly like the real API (verified against
// backend/main.py and backend/bill_audit.py), using real corpus records so
// the worst case measured is the real worst case, not a sanitised one.

export const POLICIES = {
  insurers: [
    { insurer_id: "icici_lombard", insurer: "ICICI Lombard", policies: [
      { policy_id: "icici_elevate", policy_name: "Elevate", clause_count: 227 }]},
    { insurer_id: "niva_bupa", insurer: "Niva Bupa", policies: [
      { policy_id: "niva_reassure", policy_name: "ReAssure", clause_count: 167 },
      { policy_id: "niva_reassure_30", policy_name: "ReAssure 3.0", clause_count: 153 }]},
    { insurer_id: "hdfc_ergo", insurer: "HDFC Ergo", policies: [
      { policy_id: "hdfc_optima_secure", policy_name: "Optima Secure", clause_count: 165 }]},
    { insurer_id: "tata_aig", insurer: "Tata AIG", policies: [
      { policy_id: "tata_medicare_select", policy_name: "Medicare Select", clause_count: 135 }]},
    { insurer_id: "star_health", insurer: "Star Health", policies: [
      { policy_id: "star_arogya_sanjeevani", policy_name: "Arogya Sanjeevani", clause_count: 125 }]},
  ],
};

// Verbatim from the corpus: clause 8.8 of Niva Bupa ReAssure, page 33. Chosen
// because it holds the longest unbroken tokens in the whole corpus, a 76-char
// URL and a 65-char URL. This is the real wrap hazard, not a synthetic one.
const NIVA_GRIEVANCE =
  "In case of any grievance the Insured Person may contact the company through:\n" +
  "E-mail: Email us through our service platform https://rules.nivabupa.com/customer-service/\n" +
  "Senior citizens may write to us at: seniorcitizensupport@nivabupa.com)\n" +
  "Fax : +91 11 41743397\n" +
  "opp. Metro Station, Sector 59, Noida, Uttar Pradesh, 201301\n" +
  "https:// transactions.nivabupa.com/pages/grievance-redressal.aspx\n" +
  "https://www.nivabupa.com/customer-care/health-services/grievance-\n" +
  "redressal.aspx\n" +
  "Grievance may also be lodged at IRDAI integrated Grievance Management " +
  "System – www.bimabharosa.irdai.gov.in";

// A real 293-character clause_title, the longest in the corpus.
const LONG_TITLE =
  "Any expenses incurred on prosthesis, corrective devices, external durable " +
  "medical equipment of any kind, like wheelchairs, crutches, instruments used " +
  "in treatment of sleep apnea syndrome or continuous ambulatory peritoneal " +
  "dialysis and oxygen concentrator for bronchial asthmatic condition";

export const CASE_RESULT = {
  case_id: "case_probe",
  status: "complete",
  verdict: "weakly_supported",
  confidence: 0.82,
  deciding_clauses: [
    { clause_id: "6.2.4", clause_title: LONG_TITLE,
      clause_text: NIVA_GRIEVANCE, insurer: "Niva Bupa", source_page: 33,
      exclusion_code: "Excl01", waiting_period_days: 1080,
      monetary_cap: 4500, percent_cap: 100.0 },
    { clause_id: "1.17", clause_title: "Redressal of Grievance:",
      clause_text:
        "You may register a grievance at https://www.hdfcergo.com/customer-voice/grievances " +
        "or through the IRDAI portal -https://bimabharosa.irdai.gov.in and we shall respond " +
        "within the timelines prescribed under the applicable norms on portability stipulated by IRDAI.",
      insurer: "HDFC Ergo", source_page: 41, exclusion_code: null,
      waiting_period_days: null, monetary_cap: null, percent_cap: null },
  ],
  explanation:
    "The insurer relies on the pre-existing disease exclusion, but the wording " +
    "requires the condition to have been diagnosed before inception, and the " +
    "letter does not assert a diagnosis date. Fourteen months of continuous " +
    "coverage is short of the 36-month waiting period, so the exclusion is " +
    "engaged only if the condition was in fact pre-existing.",
  what_would_change_it:
    "The date your hypertension was first diagnosed. If that is after " +
    "14 March 2025, the exclusion does not apply at all.",
  arguments: {
    insurer_position:
      "The admission for angioplasty falls within the 36-month waiting period " +
      "for pre-existing disease under Excl01, and the discharge summary records " +
      "a history of hypertension predating inception.",
    claimant_position:
      "The policy requires the disease to have been diagnosed or its signs " +
      "manifested before inception. A recorded history in a discharge summary " +
      "is not a diagnosis date, and the insurer has produced none.",
    insurer_weak_point:
      "They have asserted a pre-existing condition without producing a " +
      "diagnosis date, which the clause requires them to establish.",
    claimant_weak_point:
      "If the discharge summary does record a diagnosis before inception, " +
      "the exclusion is engaged on its plain wording.",
  },
  rejection_type: "waiting_period",
  considered_count: 15,
  appeal_available: true,
  letter_type: "appeal",
};

export const APPEAL = {
  letter_text:
    "To\nThe Grievance Officer\nNiva Bupa Health Insurance Company Limited\n\n" +
    "Subject: Appeal against repudiation of claim no. CLM/2026/0098871\n\n" +
    "Dear Sir/Madam,\n\n" +
    "I write to appeal the repudiation of the above claim, communicated to me " +
    "on 12 August 2026. The stated ground is the pre-existing disease " +
    "exclusion. The clause relied on reads:\n\n" +
    "\"Treatment of a Pre-existing Disease and its direct complications, until " +
    "the expiry of 36 months of continuous coverage after the date of " +
    "inception of the first Policy with Us.\"\n\n" +
    "A grievance may also be lodged at https://bimabharosa.irdai.gov.in and I " +
    "reserve the right to do so.\n\nYours faithfully,",
  quotes_verified: true,
  letter_type: "appeal",
};

// Long all-caps IRDAI item names are the wrap hazard on this screen.
export const BILL = {
  lines_read: 10,
  lines_flagged: 6,
  lines_not_flagged: 4,
  not_flagged: [
    { line_no: 1, description: "ROOM RENT - SINGLE PRIVATE AIR CONDITIONED DELUXE (4 DAYS)", amount: 24000 },
    { line_no: 2, description: "SURGEON CHARGES", amount: 45000 },
    { line_no: 9, description: "ICU CHARGES (2 DAYS)", amount: 30000 },
    { line_no: 10, description: "MEDICINES AND DRUGS", amount: 18500 },
  ],
  bill_total: 124620,
  flagged_share: 0.0574,
  findings: [
    { line_no: 3, description: "GLOVES", amount: 450,
      category: "not_payable", category_description: "Not payable",
      item_name: "GLOVES" },
    { line_no: 4, description: "BABY FOOD", amount: 320,
      category: "not_payable", category_description: "Not payable",
      item_name: "BABY FOOD" },
    { line_no: 8, description: "TELEPHONE CHARGES", amount: 150,
      category: "not_payable", category_description: "Not payable",
      item_name: "ANY KIT WITH NO CONSUMABLE USE (SUCH AS MEDICINE BOX, MEDICINE BAG, SURGICAL KIT ETC.) TELEPHONE/ TELEVISION CHARGES" },
    { line_no: 7, description: "AIR CONDITIONER CHARGES", amount: 3000,
      category: "subsume_room", category_description: "Part of room charge",
      item_name: "AIR CONDITIONER CHARGES (SEPARATELY BILLED, ALREADY PART OF ROOM RENT/ ROOM CATEGORY)" },
    { line_no: 5, description: "ATTENDANT CHARGES", amount: 2400,
      category: "subsume_room", category_description: "Part of room charge",
      item_name: "ATTENDANT CHARGES" },
    { line_no: 6, description: "X-RAY FILM", amount: 800,
      category: "subsume_procedure", category_description: "Part of procedure charge",
      item_name: "X-RAY FILM / X-RAY CASSETTE / DIGITAL RADIOGRAPHY CONSUMABLES" },
  ],
  by_category: [],
  flagged_total: 7120,
  findings_without_amount: 1,
  checks: {
    irdai_items: 146,
    room_rent_checked: false,
    room_rent_reason:
      "Room rent limits are set in your Policy Schedule, not in the policy wording, so they cannot be checked from the policy alone.",
  },
};
