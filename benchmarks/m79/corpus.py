"""
Twelve original fictional documents, one per report family. Every organisation, person
and figure is invented. Images are generated here; none comes from a reference document.
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFilter

from dynamic_pdf import DocumentBuilder
from dynamic_pdf.schema.media_intent import MediaIntent


# ── generated images ────────────────────────────────────────────────────────────

def _vertical(size, top, bottom):
    w, h = size
    strip = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        strip.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    return strip.resize(size)


def coast(path, size=(2000, 1300), sky=((30, 62, 98), (238, 190, 140)), sea=(26, 74, 92), land=(22, 40, 48)):
    im = _vertical(size, *sky)
    d = ImageDraw.Draw(im)
    w, h = size
    d.ellipse((w * .62, h * .24, w * .72, h * .24 + w * .10), fill=(250, 226, 180))
    d.polygon([(0, h * .62), (w * .22, h * .50), (w * .4, h * .60), (w * .66, h * .53), (w, h * .63), (w, h), (0, h)],
              fill=tuple(int(c * 1.5) for c in land))
    d.rectangle((0, h * .66, w, h), fill=sea)
    for i in range(26):
        y = h * (.68 + .012 * i)
        d.line((w * (.1 + .02 * (i % 5)), y, w * (.45 + .03 * (i % 7)), y), fill=(70, 124, 138), width=2)
    d.polygon([(0, h), (0, h * .82), (w * .3, h * .9), (w * .52, h)], fill=land)
    im.filter(ImageFilter.GaussianBlur(1.2)).save(path, dpi=(220, 220))


def works(path, size=(1600, 1200), base=((222, 228, 226), (182, 196, 194)), block=(64, 92, 104)):
    im = _vertical(size, *base)
    d = ImageDraw.Draw(im)
    w, h = size
    for i, (x, top) in enumerate([(.08, .42), (.26, .30), (.46, .48), (.62, .22), (.82, .38)]):
        d.rectangle((w * x, h * top, w * (x + .13), h * .86), fill=tuple(min(255, c + 18 * i) for c in block))
        for r in range(4):
            d.rectangle((w * (x + .03), h * (top + .06 + .1 * r), w * (x + .1), h * (top + .1 + .1 * r)), fill=(236, 226, 196))
    d.rectangle((0, h * .86, w, h), fill=(70, 78, 80))
    im.save(path, dpi=(200, 200))


def portrait_field(path, size=(1200, 1600), top=(236, 228, 208), bottom=(120, 148, 110)):
    im = _vertical(size, top, bottom)
    d = ImageDraw.Draw(im)
    w, h = size
    for i in range(9):
        x = w * (.06 + .11 * i)
        d.line((x, h, x + w * .03 * ((i % 3) - 1), h * (.38 + .04 * (i % 4))), fill=(62, 92, 66), width=14)
        d.ellipse((x - 46, h * (.34 + .04 * (i % 4)), x + 46, h * (.34 + .04 * (i % 4)) + 92), fill=(198, 150, 62))
    im.save(path, dpi=(200, 200))


def logo(path, a=(16, 86, 112), b=(208, 138, 44), size=(900, 240)):
    im = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(im)
    d.ellipse((10, 20, 210, 220), fill=a)
    d.pieslice((60, 60, 170, 170), 200, 340, fill=b)
    for i in range(3):
        d.rectangle((260, 60 + 48 * i, 860 - 120 * i, 84 + 48 * i), fill=a if i == 0 else (120, 134, 142))
    im.save(path, dpi=(300, 300))


def make_assets(folder: str) -> dict:
    os.makedirs(folder, exist_ok=True)
    paths = {k: os.path.join(folder, k + ".png") for k in ("coast", "coast2", "works", "field", "logo")}
    coast(paths["coast"])
    coast(paths["coast2"], sky=((70, 104, 120), (222, 214, 196)), sea=(52, 92, 96), land=(44, 58, 52))
    works(paths["works"])
    portrait_field(paths["field"])
    logo(paths["logo"])
    return paths


# ── helpers ─────────────────────────────────────────────────────────────────────

def photo(b, src, caption, source=None, hero=False):
    b.image(src, caption=caption, alt_text=caption, source=source,
            intent=MediaIntent(role="photo", crop_allowed=True, prominence="hero" if hero else "normal"))


def section(b, title, *parts, level=1):
    b.heading(title, level=level)
    for p in parts:
        if isinstance(p, str):
            b.paragraph(p)
        else:
            p(b)


def bars(title, data):
    return lambda b: b.chart("bar", data, title=title, legend=False)


def line(title, data):
    return lambda b: b.chart("line", data, title=title, legend=False)


def table(headers, rows, caption=None, footer=None):
    def add(b):
        b.table(headers, rows, caption=caption)
        if footer:
            b._blocks[-1].footer_row = footer
    return add


# ── documents ───────────────────────────────────────────────────────────────────

def annual_report(a):
    b = DocumentBuilder()
    b.meta(title="Saltmere Harbour Authority Annual Report 2025", subject="A working port in a changing climate",
           author="Saltmere Harbour Authority")
    section(b, "Chair's letter",
            "This was the year the harbour stopped waiting for the weather to behave. We rebuilt the north quay on a "
            "higher datum, opened the ferry terminal two months early, and held tariffs flat for the third year running. "
            "None of it was glamorous work, and nearly all of it happened at night or in the rain.",
            "Our crews logged more than eleven thousand hours on the water, and every one of those hours was completed "
            "without a lost-time injury. That record belongs to the people on the quay, not to the board, and it is the "
            "achievement I am proudest to report.",
            lambda b: b.quote("A harbour is a promise that the tide will not decide who gets to work today.",
                              attribution="Marit Oyelaran, Chair"),
            "The year ahead asks more of us. Storm surge modelling suggests the south basin needs the same treatment as "
            "the north quay within a decade, and we intend to begin that design work while the balance sheet is strong.")
    section(b, "The year in numbers",
            "Traffic recovered across every category, led by short-sea freight and the new island ferry service. "
            "Revenue growth came from volume rather than price.",
            lambda b: b.metric_row([{"label": "Vessel calls", "value": "4,218", "delta": "+6.2%"},
                                    {"label": "Freight tonnes", "value": "1.84m", "delta": "+9.1%"},
                                    {"label": "Passengers", "value": "612k", "delta": "+14.0%"},
                                    {"label": "Lost-time injuries", "value": "0"}]),
            bars("Freight handled, million tonnes", {"2021": 1.31, "2022": 1.44, "2023": 1.52, "2024": 1.69, "2025": 1.84}))
    section(b, "Rebuilding the north quay",
            lambda b: photo(b, a["coast"], "The north quay at first light, after the final deck pour", "Saltmere survey team", hero=True),
            "The quay wall dates from 1931 and had settled unevenly along most of its length. Rather than patching it again, "
            "we drove a new steel combi-wall in front of the old face and raised the deck by ninety centimetres.",
            "Working around live berths meant that no more than two of the six berths were ever closed. Pilots, stevedores "
            "and the contractor met every morning at six to agree which berth would be handed back that evening.",
            "The finished wall is designed for a century of use at the upper end of the sea-level projections. Its drainage, "
            "lighting and shore power were all replaced while the deck was open, which saved a second round of disruption.",
            "Divers surveyed the toe of the wall in October and found no scour, and the monitoring points installed during "
            "construction will report settlement every quarter for the next five years.")
    section(b, "People and safety",
            "We trained forty-one new deckhands and riggers through the apprenticeship scheme, the largest intake since it "
            "began. Fourteen of them came from the town's further education college under the bursary we fund jointly.",
            lambda b: photo(b, a["works"], "Apprentices at the rigging yard", "Saltmere communications"),
            "Near-miss reporting rose by a third, which we read as a sign of trust rather than of danger. Every report was "
            "reviewed within two working days and the outcome was posted at the gate for all crews to see.",
            "Staff turnover fell to six per cent. The revised shift pattern, agreed with the union in March, gave crews "
            "longer rest periods between night tides and has reduced overtime without reducing cover.")
    section(b, "Environment",
            "Shore power at the ferry berth now supplies all overnight loads, removing the single largest source of "
            "particulates on the waterfront. Air monitors along Quay Street recorded their lowest annual readings on file.",
            "Dredged material from the approach channel was used to restore eight hectares of salt marsh at Pellow Flats. "
            "Wading birds returned to the site within the first season, well ahead of the ecologists' forecast.",
            line("Harbour emissions, thousand tonnes CO2e", {"2021": 18.2, "2022": 17.1, "2023": 15.9, "2024": 13.8, "2025": 11.6}))
    section(b, "Financial review",
            "Operating income rose on higher berth occupancy, and maintenance spending stayed inside the approved envelope. "
            "Cash from operations covered the capital programme without new borrowing.",
            table(["Summary, £m", "2025", "2024", "Change"],
                  [["Port dues", "21.4", "19.6", "+9.2%"], ["Ferry terminal", "6.8", "5.1", "+33.3%"],
                   ["Property and leases", "4.2", "4.1", "+2.4%"], ["Operating costs", "(19.7)", "(18.9)", "+4.2%"]],
                  caption="Summary of results", footer=["Operating surplus", "12.7", "9.9", "+28.3%"]),
            "The board kept the reserve ratio above its policy floor and moved two dredging contracts to fixed-price terms.")
    section(b, "Appendix: governance",
            "The Authority is a trust port governed by an independent board of nine members. Board papers, minutes and "
            "the register of interests are published on the Authority's website after each meeting.",
            table(["Committee", "Chair", "Meetings"], [["Audit and risk", "T. Vasquez", "5"], ["Safety", "R. Lindqvist", "6"],
                                                       ["Remuneration", "M. Oyelaran", "2"]]))
    return b, {"name": "Saltmere Harbour Authority", "primary": "#124E63", "accent": "#C9822C", "logo": a["logo"]}


def financial_statements(a):
    b = DocumentBuilder()
    b.meta(title="Larkfield Infrastructure Fund Interim Statements", subject="Six months to 30 June 2025",
           author="Larkfield Capital Partners")
    section(b, "Highlights",
            "Net asset value per unit rose over the half as regulated assets delivered inflation-linked income and the "
            "fibre portfolio passed its break-even take-up. Distributions were covered by operating cash.",
            lambda b: b.metric_row([{"label": "NAV per unit", "value": "118.4p", "delta": "+3.1%"},
                                    {"label": "Distribution", "value": "3.25p", "delta": "+4.0%"},
                                    {"label": "Cash cover", "value": "1.31x"},
                                    {"label": "Gearing", "value": "27.6%", "delta": "-1.2 pts"}]))
    section(b, "Portfolio performance",
            "The fund holds fourteen operating assets across regulated water, district heat, fibre and transport. No single "
            "asset exceeds fifteen per cent of portfolio value, and sixty-eight per cent of revenue is inflation-linked.",
            table(["Asset class", "Value £m", "Share", "Yield", "Return"],
                  [["Regulated water", "412.6", "31.2%", "5.8%", "4.1%"], ["District heat", "286.0", "21.6%", "6.4%", "3.6%"],
                   ["Fibre networks", "241.9", "18.3%", "3.9%", "5.2%"], ["Transport concessions", "218.3", "16.5%", "7.1%", "2.9%"],
                   ["Renewable generation", "163.7", "12.4%", "6.9%", "1.8%"]],
                  caption="Portfolio by asset class at 30 June 2025", footer=["Total", "1,322.5", "100.0%", "5.9%", "3.7%"]),
            bars("Portfolio value by asset class, £m", {"Water": 412.6, "Heat": 286.0, "Fibre": 241.9, "Transport": 218.3, "Renewables": 163.7}),
            "Renewable generation returned least, as lower wind speeds in the second quarter reduced output by nine per cent "
            "against budget. Power price hedges covered most of the revenue shortfall.")
    section(b, "Statement of comprehensive income",
            "All amounts are in millions of pounds and are unaudited. Comparative figures are for the six months to 30 June 2024.",
            table(["£m", "H1 2025", "H1 2024"],
                  [["Investment income", "48.2", "44.7"], ["Fair value gains", "17.9", "9.3"], ["Management fees", "(6.1)", "(5.8)"],
                   ["Other expenses", "(1.4)", "(1.3)"], ["Finance costs", "(7.7)", "(8.0)"]],
                  footer=["Profit for the period", "50.9", "38.9"]))
    section(b, "Statement of financial position",
            "Investments are carried at fair value through profit or loss and were valued by the independent valuer at the balance sheet date.",
            table(["£m", "30 Jun 2025", "31 Dec 2024"],
                  [["Investments at fair value", "1,322.5", "1,271.8"], ["Cash and equivalents", "64.3", "58.0"],
                   ["Other receivables", "9.1", "8.4"], ["Borrowings", "(365.0)", "(372.5)"], ["Other payables", "(11.2)", "(10.6)"]],
                  footer=["Net assets", "1,019.7", "955.1"]))
    section(b, "Cash flow and distributions",
            "Operating cash rose on higher distributions from the regulated water holdings. The fund repaid £7.5m of its revolving "
            "facility and has £120m undrawn. The second interim distribution will be paid on 30 September.",
            line("Quarterly cash cover, times", {"Q3 23": 1.12, "Q4 23": 1.18, "Q1 24": 1.21, "Q2 24": 1.24, "Q3 24": 1.22, "Q4 24": 1.27, "Q1 25": 1.29, "Q2 25": 1.33}))
    section(b, "Appendix: notes to the statements",
            "These condensed statements were prepared in accordance with IAS 34. Accounting policies are unchanged from the "
            "last annual report. Valuation uses discounted cash flows at a weighted average discount rate of 8.4 per cent.",
            table(["Sensitivity", "NAV effect £m"], [["Discount rate +0.5%", "(46.2)"], ["Discount rate -0.5%", "49.8"],
                                                     ["Inflation +0.5%", "38.1"], ["Inflation -0.5%", "(35.4)"]]))
    return b, {"name": "Larkfield Capital Partners", "primary": "#1E3A5F", "accent": "#2E8B7A"}


def board_paper(a):
    b = DocumentBuilder()
    b.meta(title="Project Meridian: Decision Paper", subject="For decision by the Board, 14 October",
           author="Office of the Chief Operating Officer")
    section(b, "Recommendation",
            "The Board is asked to approve phase two of Project Meridian at a capped cost of £18.5m, with release of funds "
            "in three tranches tied to the milestones in this paper.",
            lambda b: b.callout("Approving now holds the supplier price until 31 December. A later decision reopens the tender and "
                                "adds an estimated eleven weeks.", title="Why now", variant="important"))
    section(b, "Where we are",
            "Phase one consolidated four regional dispatch centres into two and has run for nine months without a major "
            "incident. Average response time fell, and overtime is now below the level assumed in the business case.",
            lambda b: b.metric_row([{"label": "Response time", "value": "14m 20s", "delta": "-18%"},
                                    {"label": "Overtime", "value": "6.1%", "delta": "-2.4 pts"},
                                    {"label": "Phase one spend", "value": "£9.2m"}]),
            "The remaining benefits depend on integrating the fleet systems, which is the scope of phase two.")
    section(b, "Options considered",
            "Three options were appraised against cost, delivery risk and benefit timing. Option B is recommended.",
            table(["Option", "Cost", "Payback", "Delivery risk"],
                  [["A. Stop after phase one", "£0", "None", "Low"], ["B. Integrate fleet systems", "£18.5m", "3.4 years", "Medium"],
                   ["C. Full platform replacement", "£41.0m", "7.1 years", "High"]], caption="Options appraisal"))
    section(b, "Risks and mitigations",
            "The largest risk is data migration from the two older fleet systems. A parallel run of eight weeks is included in the plan.",
            lambda b: b.bullet_list(["Supplier capacity: named team written into the contract.",
                                     "Union consultation: joint working group in place since June.",
                                     "Benefit slippage: tranche three is released only after benefits are verified."]))
    section(b, "Next steps",
            "Subject to approval, contract signature will follow within ten working days and mobilisation will begin in November. "
            "The Audit Committee will receive a progress report each quarter.")
    return b, {"name": "Northline Transit", "primary": "#3A2E6E", "accent": "#D1495B"}


def technical_manual(a):
    b = DocumentBuilder()
    b.meta(title="Tidewatch Sensor Node Installation Manual", subject="Hardware revision C, firmware 4.2", author="Tidewatch Instruments")
    section(b, "Before you start",
            "Read this manual completely before installing a node. The node is rated for continuous immersion to ten metres, "
            "but the cable gland must be fitted exactly as described or the rating does not apply.",
            lambda b: b.callout("Disconnect the battery pack before opening the housing. The supercapacitor holds charge for up to an hour.", title="Warning", variant="warning"),
            lambda b: b.table(["Item", "Quantity", "Part number"], [["Sensor node", "1", "TW-4200"], ["Mounting bracket", "1", "TW-0112"],
                                                                    ["Cable gland M16", "2", "TW-0340"], ["Desiccant pack", "2", "TW-0091"]], caption="Contents of the kit"))
    section(b, "Mounting the node",
            "Choose a mounting point at least thirty centimetres below the lowest astronomical tide and clear of propeller wash. "
            "Fix the bracket with the four stainless bolts supplied and torque them to twelve newton-metres.",
            lambda b: b.numbered_list(["Offer the bracket to the piling and mark the four holes.", "Drill to the depth stamped on the template.",
                                       "Fit the anchors and bolt the bracket in place.", "Slide the node onto the bracket until the latch clicks."]),
            lambda b: b.image(a["works"], caption="Bracket assembly on a steel piling", alt_text="Bracket assembly",
                              intent=MediaIntent(role="diagram")))
    section(b, "Configuring the firmware",
            "Connect the service cable and open a serial session at 115200 baud. The node prints its identity and waits for commands.",
            lambda b: b.code("bash", "tw-config --port /dev/ttyUSB0 set interval 300\ntw-config --port /dev/ttyUSB0 set uplink lora\ntw-config --port /dev/ttyUSB0 commit"),
            "A committed configuration survives a battery change. Use the status command to confirm the settings took effect.",
            lambda b: b.table(["Parameter", "Default", "Range", "Unit"], [["interval", "600", "60-3600", "s"], ["uplink", "lora", "lora, nbiot", "-"],
                                                                         ["depth_offset", "0.00", "-5.00-5.00", "m"], ["salinity_comp", "on", "on, off", "-"]], caption="Configuration parameters"))
    section(b, "Maintenance",
            "Inspect the node every six months. Remove growth from the sensor face with a soft brush, and replace the desiccant packs at each opening.",
            lambda b: b.checklist([{"text": "Clean the sensor face", "checked": False}, {"text": "Replace desiccant packs", "checked": False},
                                   {"text": "Check the gland torque", "checked": False}, {"text": "Record the battery voltage", "checked": False}]))
    section(b, "Troubleshooting",
            "Most field faults trace back to the uplink or the battery rather than to the sensor itself.",
            lambda b: b.table(["Symptom", "Likely cause", "Action"], [["No uplink", "Antenna submerged", "Raise the antenna mast"],
                                                                      ["Drifting depth", "Fouled sensor face", "Clean and re-zero"],
                                                                      ["Short battery life", "Interval too low", "Increase the interval"]], caption="Common faults"))
    section(b, "Appendix: specifications",
            "All figures are typical at twenty degrees Celsius.",
            lambda b: b.table(["Specification", "Value"], [["Depth accuracy", "±2 mm"], ["Temperature range", "-5 to 45 °C"], ["Battery life", "3 years at 600 s"], ["Weight", "1.4 kg"]]))
    return b, {"name": "Tidewatch Instruments", "primary": "#0F5C5C", "accent": "#E07A1F"}


def research_paper(a):
    b = DocumentBuilder()
    b.meta(title="Shoreline Retreat and Household Relocation Choices", subject="Evidence from a stated-preference survey in three estuary towns",
           author="Ines Halvorsen and Tomasz Abara")
    b.abstract([{"label": "Background", "text": "Estuary towns face managed retreat decisions with little evidence on household preferences."},
                {"label": "Methods", "text": "We surveyed 1,204 households in three towns using a discrete choice experiment."},
                {"label": "Results", "text": "Respondents valued community continuity more than compensation above a modest threshold."}])
    section(b, "Introduction",
            "Sea-level rise is forcing coastal authorities to consider moving people rather than defending land. Most appraisal "
            "methods treat relocation as a matter of property values, yet qualitative work suggests that households weigh "
            "community ties at least as heavily as money.",
            "This paper asks how far compensation can substitute for community continuity. We report a discrete choice experiment "
            "fielded in three towns with differing flood histories, and we estimate willingness to accept for each attribute.")
    section(b, "Data and methods",
            "Households were sampled from the electoral roll within the projected 2070 flood extent. Each respondent completed "
            "eight choice tasks describing relocation packages that varied in compensation, distance, timing and neighbour retention.",
            table(["Town", "Households", "Response rate", "Flooded since 2000"],
                  [["Eastwick", "402", "41%", "Twice"], ["Marrow Bay", "388", "37%", "Once"], ["Pellow", "414", "44%", "Never"]], caption="Sample by town"),
            "We estimated a mixed logit model with normally distributed coefficients for the non-monetary attributes, using five hundred Halton draws.")
    section(b, "Results",
            "Neighbour retention was the strongest non-monetary attribute in every town. Moving as a group raised the probability "
            "of choosing a package by twenty-three percentage points, equivalent to a substantial share of average compensation.",
            bars("Effect on choice probability, percentage points", {"Group move": 23, "Under 5 km": 17, "Earlier date": 6, "+10% payment": 9}),
            table(["Attribute", "Coefficient", "Std. error", "p"],
                  [["Compensation (10k)", "0.214", "0.031", "<0.001"], ["Neighbours retained", "0.842", "0.066", "<0.001"],
                   ["Distance (10 km)", "-0.337", "0.044", "<0.001"], ["Move within 5 years", "-0.121", "0.052", "0.020"]], caption="Mixed logit estimates"),
            "Flood experience changed the timing attribute but not the others. Households in Eastwick preferred earlier moves, while those in Pellow preferred to wait.")
    section(b, "Discussion",
            "These results suggest that buyout schemes built around individual payments may be poorly matched to what households want. "
            "Group relocation is more expensive to organise, but our estimates imply it could reduce the compensation required.",
            "Stated preferences are not observed behaviour, and the survey frame excludes renters who moved in after the roll was compiled.")
    section(b, "Conclusion",
            "Community continuity is a first-order concern in managed retreat. Appraisal guidance should treat it as such.")
    section(b, "References",
            lambda b: b.bibliography([
                {"key": "abara2023", "authors": "Abara, T.", "title": "Retreat without leaving",
                 "source": "Journal of Coastal Policy 12(2)", "year": "2023"},
                {"key": "halvorsen2022", "authors": "Halvorsen, I. and Lund, P.", "title": "Choice models for relocation",
                 "source": "Estuarine Economics 8(1)", "year": "2022"}]))
    return b, {}


def proposal(a):
    b = DocumentBuilder()
    b.meta(title="Rewilding the Pellow Marshes", subject="A proposal to the Coastal Futures Fund", author="Fernhollow Studio")
    section(b, "The opportunity",
            "Pellow Flats is the largest unprotected salt marsh left on this coast. Eight hectares have already recovered with "
            "almost no intervention. With modest support, the remaining forty could become a working example of nature-based defence.",
            lambda b: photo(b, a["coast2"], "Pellow Flats at low water, looking east", "Fernhollow Studio", hero=True),
            "We propose a five-year programme that combines habitat restoration with public access, and that leaves the site in the "
            "hands of a local trust rather than a consultancy.")
    section(b, "Our approach",
            "Marshes rebuild themselves when sediment and water are allowed to move. Our design removes two failed embankments, "
            "opens three creek lines and raises a single low bund to protect the access road.",
            lambda b: photo(b, a["field"], "Sea purslane recolonising the first restored cell", "Fernhollow Studio"),
            "Every intervention is reversible for the first three years, so the design can respond to what the marsh actually does. "
            "Monitoring is carried out by trained volunteers working with the university's estuary lab, and their data is published openly.",
            "Paths, hides and a small learning shelter are built from local timber, keeping the visitor footprint to the landward edge "
            "and leaving the creeks undisturbed during the breeding season.")
    section(b, "Programme",
            "The work is sequenced so that the first visible results arrive inside eighteen months.",
            lambda b: b.timeline([{"date": "2026", "title": "Survey and consents", "description": "Baseline surveys, licences and landowner agreements."},
                                  {"date": "2027", "title": "Breach and creeks", "description": "Embankments removed and creek lines opened."},
                                  {"date": "2028", "title": "Access", "description": "Paths, hides and shelter completed."},
                                  {"date": "2030", "title": "Handover", "description": "Site passes to the Pellow Marshes Trust."}]))
    section(b, "Budget",
            "We are requesting £1.24m over five years, with a further £310k secured from the county council.",
            table(["Work package", "2026-27", "2028-30", "Total"],
                  [["Survey and design", "£180k", "£40k", "£220k"], ["Earthworks", "£520k", "£60k", "£580k"],
                   ["Access and learning", "£90k", "£260k", "£350k"], ["Monitoring and trust setup", "£110k", "£290k", "£400k"]],
                  caption="Budget by work package", footer=["Total", "£900k", "£650k", "£1.55m"]))
    section(b, "Team",
            "Fernhollow Studio has restored eleven coastal sites in the past decade. Our lead ecologist, Dr Amara Fenwick, has "
            "worked on the Pellow estuary for fifteen years, and our landscape architect led the award-winning Sallow Point scheme.")
    return b, {"name": "Fernhollow Studio", "primary": "#2F5D50", "accent": "#C8553D", "logo": a["logo"]}


def impact_report(a):
    b = DocumentBuilder()
    b.meta(title="Open Water Impact Report", subject="What your support made possible in 2025", author="The Open Water Trust")
    section(b, "A year on the water",
            "Six thousand young people learned to swim, row or sail with us this year, and for most of them it was the first time "
            "they had been out on the water at all. That number matters less than what they told us afterwards.",
            lambda b: photo(b, a["coast"], "Evening session at Eastwick slipway", "Open Water Trust", hero=True),
            lambda b: b.quote("I didn't know I lived near the sea until I was on it.", attribution="Year 9 participant, Eastwick"))
    section(b, "What changed",
            "We ask every participant the same questions before and after a season. Confidence rose most among those who began as non-swimmers.",
            lambda b: b.metric_row([{"label": "Young people reached", "value": "6,140"}, {"label": "First-time swimmers", "value": "71%"},
                                    {"label": "Volunteer hours", "value": "22,600"}, {"label": "Partner schools", "value": "48"}]),
            bars("Share reporting confidence on the water, %", {"Before": 34, "After": 82}))
    section(b, "Stories from the slipway",
            "Dara joined the Saturday rowing group when her school closed its pool. Eight months later she coxed the junior crew at the "
            "county regatta, and she now helps new starters with their first capsize drill.",
            lambda b: photo(b, a["field"], "The Pellow youth crew's training ground", "Open Water Trust"),
            "At Marrow Bay, the Trust and the local mosque set up women-only swimming sessions that filled within a week. Thirty-two mothers "
            "learned to swim alongside their daughters, and six have since qualified as session assistants.",
            "Our volunteers are the reason any of this works. Retired fishermen, teachers and a surprising number of accountants gave up "
            "their weekends to stand in cold water and teach someone to float.")
    section(b, "How we spent your money",
            "Eighty-four pence of every pound went directly to programmes.",
            table(["Spending", "£000", "Share"], [["Programmes", "1,412", "84%"], ["Fundraising", "168", "10%"], ["Governance", "101", "6%"]], footer=["Total", "1,681", "100%"]))
    section(b, "What comes next",
            "Next year we will open two new sites and train a further sixty instructors. If you would like to volunteer, or to fund a place, please get in touch.")
    return b, {"name": "The Open Water Trust", "primary": "#0B6E8F", "accent": "#F2A541", "logo": a["logo"]}


def policy_brief(a):
    b = DocumentBuilder()
    b.meta(title="Flood Insurance for Small Businesses", subject="Policy brief 2025/07", author="Institute for Coastal Economy")
    section(b, "Summary",
            "Small coastal businesses are three times more likely than households to be uninsured against flood. A targeted reinsurance "
            "scheme could close most of the gap at modest public cost.",
            lambda b: b.callout("Extend the existing household reinsurance pool to businesses with fewer than fifty staff, phased over three years.", title="Recommendation", variant="tip"))
    section(b, "The problem",
            "Insurers have withdrawn from high-risk postcodes faster than businesses have been able to adapt. After the 2024 surge, "
            "four in ten affected firms on the east coast had no cover, and one in five had not reopened a year later.",
            bars("Uninsured against flood, %", {"Households": 7, "Micro firms": 26, "Small firms": 21, "Medium firms": 9}),
            "The loss is not only private. Each closed high-street business reduces footfall for its neighbours and weakens the local tax base.")
    section(b, "Options",
            "We assessed three approaches against coverage, cost and moral hazard.",
            table(["Option", "Coverage gain", "Annual cost", "Moral hazard"], [["Tax relief on premiums", "Low", "£12m", "Low"],
                                                                               ["Extend reinsurance pool", "High", "£28m", "Medium"],
                                                                               ["Direct public insurance", "High", "£95m", "High"]], caption="Options compared"))
    section(b, "Recommendation",
            "Extending the pool offers the best balance. Premium discounts should be tied to resilience measures so that public money also reduces future losses.")
    return b, {"name": "Institute for Coastal Economy", "primary": "#7A2E3A", "accent": "#3C6E71"}


AR_P = [
    "شهد عام ٢٠٢٥ توسعًا ملحوظًا في خدمات الهيئة، إذ اكتمل تحديث شبكة المياه في المنطقة الشرقية، وبدأ تشغيل محطة المعالجة الجديدة قبل موعدها بشهرين. وقد انعكس ذلك مباشرة على جودة الخدمة المقدمة للسكان في الأحياء الساحلية.",
    "تَعْمَلُ الهَيْئَةُ عَلَى تَطْوِيرِ البِنْيَةِ التَّحْتِيَّةِ بِمَا يَضْمَنُ اسْتِدَامَةَ الخِدْمَاتِ لِلْأَجْيَالِ القَادِمَةِ، وَتَلْتَزِمُ بِالشَّفَافِيَةِ الكَامِلَةِ فِي نَشْرِ نَتَائِجِهَا.",
    "استثمرت الهيئة في تدريب كوادرها الوطنية، فالتحق أكثر من مئتي موظف ببرامج التأهيل الفني والإداري خلال العام، وارتفعت نسبة التوطين في الوظائف التخصصية إلى مستوى غير مسبوق في تاريخها.",
    "وعلى صعيد الاستدامة، خفضت المحطات استهلاكها من الطاقة بفضل نظم الاسترجاع الحراري الجديدة، وأعيد استخدام المياه المعالجة في ري الحدائق العامة والمساحات الخضراء على امتداد الواجهة البحرية.",
    "تواصل الهيئة العمل مع الجهات الشريكة لضمان جاهزية الشبكات لمواسم الأمطار، وقد أجرت خلال العام مراجعة شاملة لخطط الطوارئ، وأجرت تمارين ميدانية مشتركة في ثلاث مناطق.",
    "وتتطلع الهيئة في العام المقبل إلى إطلاق المرحلة الثانية من مشروع العدادات الذكية، بما يتيح للمشتركين متابعة استهلاكهم لحظة بلحظة، ويساعد فرق التشغيل على اكتشاف التسربات في وقت مبكر.",
]


def arabic_annual(a):
    b = DocumentBuilder()
    b.direction("rtl")
    b.meta(title="التقرير السنوي لهيئة مياه الساحل ٢٠٢٥", subject="خدمة مستدامة لمجتمع متنامٍ", author="هيئة مياه الساحل")
    section(b, "كلمة رئيس مجلس الإدارة", AR_P[0], AR_P[1],
            lambda b: b.quote("الماء أمانة، وحسن إدارته مسؤولية نحملها جيلًا بعد جيل.", attribution="سالم الحارثي، رئيس مجلس الإدارة"), AR_P[5])
    section(b, "أبرز الأرقام", "حققت الهيئة خلال العام نتائج تشغيلية قوية في جميع القطاعات الرئيسية.",
            lambda b: b.metric_row([{"label": "المشتركون", "value": "٤١٢ ألف", "delta": "+٦٪"}, {"label": "المياه المنتجة", "value": "٩٨ مليون م³"},
                                    {"label": "نسبة الفاقد", "value": "١١٪", "delta": "-٢٪"}, {"label": "رضا العملاء", "value": "٩٢٪"}]))
    section(b, "مشاريع البنية التحتية",
            lambda b: photo(b, a["coast"], "محطة المعالجة الجديدة على الواجهة البحرية", "فريق التوثيق في الهيئة", hero=True),
            AR_P[0], AR_P[4], AR_P[3])
    section(b, "الموارد البشرية", AR_P[2], AR_P[1],
            lambda b: photo(b, a["works"], "ورشة تدريب الكوادر الفنية", "فريق التوثيق في الهيئة"), AR_P[2])
    section(b, "النتائج المالية", "ارتفعت الإيرادات التشغيلية مع الحفاظ على الانضباط في المصروفات خلال السنة المالية.",
            table(["البند (مليون ريال)", "٢٠٢٥", "٢٠٢٤", "التغير"],
                  [["إيرادات المياه", "٢١٤٫٦", "١٩٨٫٢", "+٨٫٣٪"], ["إيرادات الصرف", "٨٧٫٤", "٨١٫٠", "+٧٫٩٪"], ["مصروفات التشغيل", "(١٩٢٫٨)", "(١٨٤٫٥)", "+٤٫٥٪"]],
                  caption="ملخص النتائج المالية", footer=["الفائض التشغيلي", "١٠٩٫٢", "٩٤٫٧", "+١٥٫٣٪"]), AR_P[4])
    section(b, "ملحق: الحوكمة", "يتولى مجلس الإدارة الإشراف على أعمال الهيئة من خلال ثلاث لجان منبثقة عنه.",
            table(["اللجنة", "الرئيس", "عدد الاجتماعات"], [["المراجعة", "ليلى العامري", "٥"], ["المخاطر", "خالد الزدجالي", "٤"]]))
    return b, {"name": "هيئة مياه الساحل", "primary": "#0E5A6B", "accent": "#B8862D", "logo": a["logo"]}


def arabic_financial(a):
    b = DocumentBuilder()
    b.direction("rtl")
    b.meta(title="القوائم المالية الموجزة لصندوق الوفاء", subject="للفترة المنتهية في ٣٠ يونيو ٢٠٢٥", author="شركة الوفاء لإدارة الأصول")
    section(b, "ملخص الأداء", "حقق الصندوق عائدًا إيجابيًا خلال الفترة مدعومًا بأداء قطاع العقارات اللوجستية، مع المحافظة على مستوى متحفظ من المديونية.",
            lambda b: b.metric_row([{"label": "صافي قيمة الوحدة", "value": "١٢٫٤٨ ريال", "delta": "+٣٫٢٪"}, {"label": "التوزيعات", "value": "٠٫٣٥ ريال"}, {"label": "نسبة المديونية", "value": "٢٤٪"}]))
    section(b, "قائمة المركز المالي", "تظهر الأرقام بملايين الريالات ولم تخضع للمراجعة.",
            table(["البند", "٣٠ يونيو ٢٠٢٥", "٣١ ديسمبر ٢٠٢٤"],
                  [["الاستثمارات العقارية", "٨٤٢٫٦", "٨١٠٫٣"], ["النقد وما في حكمه", "٣٨٫٤", "٤٤٫١"], ["ذمم مدينة", "١٢٫٧", "١١٫٢"], ["قروض طويلة الأجل", "(٢١٠٫٠)", "(٢١٥٫٠)"]],
                  footer=["صافي الأصول", "٦٨٣٫٧", "٦٥٠٫٦"]))
    section(b, "قائمة الدخل", "ارتفع الدخل التشغيلي نتيجة تجديد عقود الإيجار بأسعار أعلى في المناطق الصناعية.",
            table(["البند", "النصف الأول ٢٠٢٥", "النصف الأول ٢٠٢٤"], [["إيرادات الإيجار", "٤٦٫٢", "٤١٫٨"], ["مصروفات التشغيل", "(٩٫٤)", "(٨٫٧)"], ["تكاليف التمويل", "(٦٫١)", "(٦٫٥)"], ["أرباح إعادة التقييم", "١٨٫٣", "١٢٫١"]],
                  footer=["صافي الربح", "٤٩٫٠", "٣٨٫٧"]),
            bars("صافي الربح (مليون ريال)", {"2022": 31, "2023": 35, "2024": 39, "2025": 49}))
    section(b, "ملحق: الإيضاحات", "أعدت هذه القوائم الموجزة وفقًا لمعيار المحاسبة الدولي رقم ٣٤، وتُقرأ مع القوائم المالية السنوية الأخيرة.")
    return b, {"name": "شركة الوفاء لإدارة الأصول", "primary": "#1F4E3D", "accent": "#A67C2D"}


def bilingual_institutional(a):
    b = DocumentBuilder()
    b.meta(title="Gulf Coast Heritage Commission | هيئة تراث ساحل الخليج", subject="Annual statement 2025 | البيان السنوي ٢٠٢٥", author="Gulf Coast Heritage Commission")
    section(b, "Our mission | رسالتنا",
            "The Commission protects the living heritage of the coast: its boatbuilding yards, pearl-diving songs and fishing villages.",
            "تحمي الهيئة التراث الحي للساحل: أحواض بناء السفن، وأهازيج الغوص، وقرى الصيادين التي شكّلت هوية المنطقة عبر القرون.",
            lambda b: photo(b, a["coast2"], "Restored boatyard at Ras Dhiyab | حوض السفن المرمم في رأس ذياب", "Commission archive", hero=True))
    section(b, "The year in brief | العام في سطور",
            "Eleven historic sites were restored, and the oral history archive passed four thousand recordings.",
            "رُمّم أحد عشر موقعًا تاريخيًا، وتجاوز أرشيف التاريخ الشفهي أربعة آلاف تسجيل.",
            lambda b: b.metric_row([{"label": "Sites restored | مواقع مرممة", "value": "11"}, {"label": "Recordings | تسجيلات", "value": "4,120"}, {"label": "Visitors | زوار", "value": "218k"}]))
    section(b, "Programmes | البرامج",
            "The master builders programme paired six elders with twenty-four apprentices, keeping traditional dhow construction alive in two yards.",
            "جمع برنامج البنّائين المهرة ستة من كبار الحرفيين مع أربعة وعشرين متدربًا، حفاظًا على صناعة السفن التقليدية في حوضين.",
            lambda b: photo(b, a["works"], "Apprentices in the yard | المتدربون في الحوض", "Commission archive"),
            "School visits resumed in full, with more than nine thousand pupils taking part in heritage days along the coast.",
            "استؤنفت الزيارات المدرسية بالكامل، وشارك أكثر من تسعة آلاف طالب في أيام التراث على امتداد الساحل.")
    section(b, "Finance | المالية",
            "Income rose with visitor numbers, and restoration spending stayed within budget.",
            "ارتفعت الإيرادات مع زيادة عدد الزوار، وبقي الإنفاق على الترميم ضمن الميزانية.",
            table(["Item | البند", "2025", "2024"], [["Government grant | المنحة الحكومية", "14.2", "13.8"], ["Visitor income | إيرادات الزوار", "3.6", "2.9"], ["Restoration | الترميم", "(11.4)", "(10.2)"]],
                  caption="Summary, million | ملخص بالمليون", footer=["Net | الصافي", "6.4", "6.5"]))
    return b, {"name": "Gulf Coast Heritage Commission", "primary": "#6B3F1D", "accent": "#1F7A8C", "logo": a["logo"]}


def sustainability_report(a):
    b = DocumentBuilder()
    b.meta(title="Brightwater Foods Sustainability Report", subject="Progress against our 2030 commitments", author="Brightwater Foods")
    section(b, "Our commitments",
            "We set three commitments in 2021: halve operational emissions, send nothing to landfill and pay a living wage across our "
            "direct supply chain. This report sets out what we achieved, and where we fell short.",
            lambda b: b.metric_row([{"label": "Scope 1+2 emissions", "value": "-38%", "delta": "vs 2021"}, {"label": "Waste to landfill", "value": "4.2%"}, {"label": "Suppliers at living wage", "value": "76%"}]),
            lambda b: b.quote("We would rather publish an honest miss than a tidy story.", attribution="Priya Nair, Chief Executive"))
    section(b, "Climate",
            "Heat recovery at the Dunmore bakery and a switch to renewable power contracts delivered most of this year's reduction. "
            "Scope 3 emissions rose by two per cent as volumes grew, and remain the hardest part of the problem.",
            line("Scope 1 and 2 emissions, thousand tonnes CO2e", {"2021": 84, "2022": 77, "2023": 68, "2024": 59, "2025": 52}),
            "We have asked our twenty largest ingredient suppliers to set science-based targets by the end of next year. Eleven have done so.",
            lambda b: b.table(["Scope", "2021", "2024", "2025"], [["Scope 1", "51", "36", "31"], ["Scope 2", "33", "23", "21"], ["Scope 3", "612", "618", "631"]], caption="Emissions by scope, thousand tonnes CO2e"))
    section(b, "Waste and packaging",
            "Landfill waste fell again, but we missed our recyclable packaging target because the replacement film for frozen lines failed shelf-life tests.",
            lambda b: photo(b, a["works"], "Sorting line at the Dunmore site", "Brightwater Foods"),
            "Surplus food donations reached nine hundred tonnes, the equivalent of over two million meals.")
    section(b, "People and suppliers",
            "All directly employed staff are paid at or above the living wage. Across direct suppliers the figure is seventy-six per cent, and we now audit the remainder annually.",
            bars("Suppliers at living wage, %", {"2022": 41, "2023": 55, "2024": 68, "2025": 76}))
    section(b, "Appendix: data tables",
            "All data covers the financial year to 31 March and has been assured to limited assurance.",
            table(["Metric", "Unit", "2024", "2025"], [["Energy use", "GWh", "212", "198"], ["Water use", "ML", "1,640", "1,510"], ["Food surplus donated", "t", "760", "905"], ["Lost-time incidents", "n", "14", "9"]]))
    return b, {"name": "Brightwater Foods", "primary": "#1F6F54", "accent": "#E3A72F", "logo": a["logo"]}


def harbour_feature(a):
    b = DocumentBuilder()
    b.meta(title="The Long Tide", subject="A year on the Saltmere waterfront", author="Saltmere Harbour Trust")
    section(b, "A working shore",
            "Saltmere has earned its living from the water for three centuries, and the shore still looks like it. Nets dry beside the slipways, and the ferry horn sets the hours for the whole town.",
            lambda b: photo(b, a["coast"], "Evening over the outer mole.", "Trust archive", hero=True),
            "When the old fish market closed, nobody expected the quay to come back. Ten years later it holds a boatyard, a cooperative smokehouse and a school of navigation for local teenagers.",
            "Most of that change came from small decisions rather than one grand plan. Each tenant signed a short lease, and each lease asked for one thing: that the public could walk the water's edge.")
    section(b, "The people of the quay",
            lambda b: photo(b, a["works"], "Shed four, repaired by its own tenants.", "Trust archive"),
            "Shed four was a ruin in 2019. Its tenants rebuilt the roof themselves and now repair forty boats a year for owners along the estuary.",
            "Ines Marlow runs the yard with her two brothers, and she takes on one apprentice every spring. Three of those apprentices now run yards of their own, and two of them came back to the quay.",
            "The smokehouse works on a different rhythm, with early starts and short days. Its seven members share one oven, one van and a long argument about the right kind of oak.")
    section(b, "Weather and water",
            lambda b: photo(b, a["coast2"], "The new tidal gate at slack water.", "Trust archive"),
            "Two winters of surge tides changed the argument about flood defence. The new tidal gate closes in eleven minutes and has already held back four storms.",
            "The gate cost less than a sea wall and leaves the view alone. It also needs a crew, which gave the harbour six permanent jobs and an excuse to keep the old lookout tower open.",
            lambda b: b.quote("You cannot wall off a town that lives from the water."),
            "Engineers expect the sea to rise a further twenty centimetres by mid-century. The gate was built for twice that, and the trust has set aside money each year for its upkeep.")
    section(b, "What comes next",
            lambda b: photo(b, a["field"], "Saltings at the north end, planted in 2024.", "Trust archive"),
            "The north saltings were replanted last year and already shelter wading birds through the winter. Volunteers count them every month and publish the numbers on the harbour wall.",
            "Next year the trust will open the lookout tower as a small museum of the estuary. Its first exhibition will be the logbooks of the harbour masters, read aloud by their descendants.")
    return b, {"name": "Saltmere Harbour Trust", "primary": "#1E4D5C", "accent": "#C8553D", "logo": a["logo"]}


def transit_data_story(a):
    b = DocumentBuilder()
    b.meta(title="Moving Brackwater", subject="Regional transit data review 2025", author="Brackwater Transit Authority")
    section(b, "How the year looked",
            "Ridership passed its pre-pandemic level for the first time, with the strongest growth on the two new tram lines. Reliability improved on every mode, though buses still lag at the evening peak.",
            lambda b: b.metric_row([{"label": "Trips", "value": "148m"}, {"label": "On time", "value": "91%"}, {"label": "Satisfaction", "value": "78%"}]),
            lambda b: b.heading("Trips by mode, millions", 2),
            bars("Tram", {"2022": 31, "2023": 38, "2024": 44, "2025": 52}),
            bars("Bus", {"2022": 62, "2023": 66, "2024": 68, "2025": 71}),
            bars("Ferry", {"2022": 7, "2023": 8, "2024": 9, "2025": 9}),
            bars("Cycle hire", {"2022": 9, "2023": 11, "2024": 14, "2025": 16}),
            "Trams now carry more than a third of all trips. Bus growth has slowed as passengers move to the tram corridors, which is what the network plan intended.")
    section(b, "Reliability",
            "Punctuality rose on every mode. The largest gain came from signal priority at forty junctions on the eastern corridor, where tram journey times fell by nine percent.",
            lambda b: b.heading("Share of services on time, percent", 2),
            line("Morning peak", {"Q1": 86, "Q2": 88, "Q3": 90, "Q4": 92}),
            line("Evening peak", {"Q1": 79, "Q2": 81, "Q3": 84, "Q4": 85}),
            line("Off peak", {"Q1": 93, "Q2": 94, "Q3": 94, "Q4": 95}),
            "The evening peak remains the weak point. Crews finishing their shifts at five o'clock leave gaps on the longest routes, and the new rosters address that from April.",
            table(["Line", "Trips (m)", "On time", "Cost per trip"],
                  [["Tram 1", "29.4", "94%", "1.10"], ["Tram 2", "22.6", "93%", "1.24"], ["Bus 12", "8.1", "86%", "1.92"], ["Bus 40", "6.7", "84%", "2.05"], ["Harbour ferry", "9.2", "96%", "3.40"]],
                  caption="Busiest services, 2025"))
    section(b, "Who rides",
            "A new travel survey reached eleven thousand residents. Younger riders use trams and cycle hire most; older riders still prefer the bus, and they value a seat more than speed.",
            lambda b: b.heading("Share of residents who use each mode weekly, percent", 2),
            bars("Under 30", {"Tram": 48, "Bus": 31, "Cycle": 22}),
            bars("30 to 59", {"Tram": 37, "Bus": 29, "Cycle": 12}),
            bars("60 and over", {"Tram": 21, "Bus": 44, "Cycle": 3}),
            "Fare capping reached full coverage in June. Riders on low incomes now pay no more than the weekly cap, and four in ten of them reached it at least once.")
    section(b, "Costs and carbon",
            "Operating cost per trip fell for the second year as ridership grew faster than service hours. Electric vehicles now run a little over half of all bus kilometres.",
            lambda b: b.heading("Two measures of efficiency", 2),
            line("Operating cost per trip", {"2022": 2.3, "2023": 2.1, "2024": 1.9, "2025": 1.8}),
            line("Grams of carbon per passenger kilometre", {"2022": 62, "2023": 55, "2024": 47, "2025": 41}),
            "The authority will publish these figures every quarter from next year, with the raw data, so that residents can check the claims made here.")
    return b, {"name": "Brackwater Transit Authority", "primary": "#20407A", "accent": "#E0A030", "logo": a["logo"]}


def arabic_city_feature(a):
    b = DocumentBuilder()
    b.direction("rtl")
    b.meta(title="مدينة على الضفتين", subject="عام في حياة واحة النخيل", author="بلدية واحة النخيل")
    section(b, "ذاكرة المكان",
            "نشأت واحة النخيل حول عين ماء قديمة، ثم امتدت على ضفتي الوادي جيلًا بعد جيل. وما زالت الأسواق القديمة تفتح أبوابها مع أذان الفجر، وما زال أهل المدينة يقيسون المسافات بعدد البساتين.",
            lambda b: photo(b, a["coast"], "غروب الشمس على ضفة الوادي الشرقية.", "أرشيف البلدية", hero=True),
            "حين أغلقت السوق القديمة قبل عشر سنوات، ظن كثيرون أن زمنها انتهى. لكن الحرفيين عادوا إليها واحدًا تلو الآخر، حتى امتلأت دكاكينها من جديد بالنحاس والخوص والعطور.",
            "لم يأت هذا التحول من خطة كبرى، بل من قرارات صغيرة متتابعة. فقد خفضت البلدية إيجار الدكاكين لكل من يعلّم حرفته لشاب من أبناء الحي.")
    section(b, "أهل السوق",
            lambda b: photo(b, a["works"], "ورشة النحاس بعد ترميم سقفها.", "أرشيف البلدية"),
            "كانت ورشة النحاس مهجورة قبل خمسة أعوام. أعاد أصحابها بناء سقفها بأيديهم، وهي اليوم تدرّب اثني عشر شابًا كل عام على مهنة كادت تندثر.",
            "يدير العم صالح الورشة منذ أربعين عامًا، ويقول إن الصنعة لا تُحفظ في الكتب بل في الأيدي. وقد افتتح ثلاثة من تلاميذه ورشًا خاصة بهم في الأحياء المجاورة.",
            "أما سوق العطارين فله إيقاع آخر، إذ يبدأ بعد العصر ويمتد حتى منتصف الليل. ويتشارك أصحابه مخزنًا واحدًا وعربة واحدة وجدلًا طويلًا حول أفضل أنواع اللبان.")
    section(b, "الماء والبساتين",
            lambda b: photo(b, a["coast2"], "قناة الري الجديدة عند موسم الفيضان.", "أرشيف البلدية"),
            "غيّر فيضانان متتاليان طريقة تفكير المدينة في الماء. فأُعيد فتح الأفلاج القديمة إلى جانب قناة جديدة، ونجت البساتين من أربع موجات سيول خلال عامين.",
            "كلفت القناة أقل مما كان متوقعًا، ولم تحجب منظر الوادي عن أهله. ووفرت كذلك ست وظائف دائمة لحراس الماء، وهي مهنة قديمة عادت بعد غياب طويل.",
            lambda b: b.quote("لا تُبنى مدينة تعيش من الماء بالجدران وحدها."),
            "يتوقع المهندسون أن تزداد حدة السيول في العقود القادمة. لذلك صُممت القناة لتحمل ضعف أعلى منسوب مسجّل، وخصصت البلدية ميزانية سنوية لصيانتها.")
    section(b, "ما ينتظرنا",
            lambda b: photo(b, a["field"], "البساتين الشمالية بعد زراعتها في عام ٢٠٢٤.", "أرشيف البلدية"),
            "زُرعت البساتين الشمالية في العام الماضي، وصارت تؤوي الطيور المهاجرة طوال الشتاء. ويعدّها المتطوعون كل شهر وينشرون الأرقام على جدار السوق.",
            "ستفتتح البلدية في العام القادم برج المراقبة القديم متحفًا صغيرًا للوادي. وسيضم معرضه الأول سجلات حراس الماء، يقرؤها أحفادهم بأصواتهم.")
    return b, {"name": "بلدية واحة النخيل", "primary": "#2F5D50", "accent": "#B8782E", "logo": a["logo"]}


def arabic_health_data(a):
    b = DocumentBuilder()
    b.direction("rtl")
    b.meta(title="صحة المجتمع بالأرقام", subject="التقرير الإحصائي السنوي ٢٠٢٥", author="هيئة الرعاية الصحية الأولية")
    section(b, "ملامح العام",
            "ارتفع عدد المراجعين في مراكز الرعاية الأولية للعام الثالث على التوالي، وتراجع متوسط زمن الانتظار بعد توسيع المواعيد المسائية. وما زالت المراكز الريفية بحاجة إلى مزيد من الأطباء.",
            lambda b: b.metric_row([{"label": "مراجعة", "value": "٢٫٤ مليون"}, {"label": "مركزًا صحيًا", "value": "٦٨"}, {"label": "نسبة الرضا", "value": "٨٤٪"}]),
            lambda b: b.heading("المراجعات حسب نوع الخدمة بالألف", 2),
            bars("طب الأسرة", {"2022": 910, "2023": 980, "2024": 1040, "2025": 1120}),
            bars("الأمومة والطفولة", {"2022": 310, "2023": 330, "2024": 345, "2025": 362}),
            bars("الأمراض المزمنة", {"2022": 420, "2023": 470, "2024": 515, "2025": 560}),
            bars("الصحة النفسية", {"2022": 60, "2023": 84, "2024": 112, "2025": 146}),
            "تضاعفت مراجعات الصحة النفسية تقريبًا خلال ثلاث سنوات، بعد إدخال الخدمة في جميع المراكز الكبرى. ويعكس ذلك استعدادًا أكبر لدى الناس لطلب المساعدة.")
    section(b, "جودة الخدمة",
            "تحسّن زمن الانتظار في كل المناطق. وجاء أكبر تحسن من نظام الحجز الإلكتروني الذي عُمّم في شهر مارس، إذ انخفض متوسط الانتظار في المراكز الحضرية بنسبة الربع.",
            lambda b: b.heading("متوسط زمن الانتظار بالدقائق", 2),
            line("المراكز الحضرية", {"الربع ١": 42, "الربع ٢": 37, "الربع ٣": 33, "الربع ٤": 31}),
            line("المراكز الريفية", {"الربع ١": 55, "الربع ٢": 52, "الربع ٣": 48, "الربع ٤": 46}),
            "لا تزال الفجوة بين المدينة والريف قائمة، ويعود معظمها إلى نقص أطباء الأسرة. وستبدأ الهيئة في الخريف برنامج حوافز للعمل في المناطق البعيدة.",
            table(["المنطقة", "المراكز", "المراجعات بالألف", "الأطباء لكل ألف"],
                  [["الوسطى", "٢٤", "٩٨٠", "١٫٤"], ["الشمالية", "١٨", "٦١٠", "١٫١"], ["الساحلية", "١٥", "٥٢٠", "١٫٠"], ["الجنوبية", "١١", "٢٩٠", "٠٫٧"]],
                  caption="الخدمات حسب المنطقة في عام ٢٠٢٥"))
    section(b, "الوقاية",
            "بلغت تغطية التطعيم للأطفال مستوى غير مسبوق، وزادت الفحوص المبكرة للسكري بعد الحملة التي نُفذت في أماكن العمل. وتراجع معدل التدخين بين الشباب للعام الخامس.",
            lambda b: b.heading("مؤشرات الوقاية بالنسبة المئوية", 2),
            line("تغطية التطعيم", {"2022": 91, "2023": 93, "2024": 95, "2025": 97}),
            line("الفحص المبكر للسكري", {"2022": 38, "2023": 44, "2024": 51, "2025": 58}),
            line("التدخين بين الشباب", {"2022": 22, "2023": 20, "2024": 18, "2025": 16}),
            "ستنشر الهيئة هذه الأرقام كل ربع سنة ابتداءً من العام القادم، مع البيانات الكاملة لكل منطقة، حتى يتمكن الباحثون والجمهور من مراجعتها.")
    return b, {"name": "هيئة الرعاية الصحية الأولية", "primary": "#124E66", "accent": "#2E9C8F", "logo": a["logo"]}


def bilingual_ports_review(a):
    b = DocumentBuilder()
    b.meta(title="Northern Ports Authority | هيئة الموانئ الشمالية", subject="Annual review 2025 | المراجعة السنوية ٢٠٢٥", author="Northern Ports Authority")
    section(b, "Chair's statement | كلمة الرئيس",
            "The year tested our ports and our people. Two storms closed the northern terminal for nine days, and yet cargo volumes ended the year higher than any year on record.",
            "كان هذا العام اختبارًا لموانئنا ولفرق العمل فيها. فقد أغلقت عاصفتان المحطة الشمالية تسعة أيام، ومع ذلك أنهينا العام بأعلى حجم مناولة في تاريخ الهيئة.",
            "We owe that result to the crews who reopened the berths ahead of schedule, and to customers who stayed with us while they did.",
            "ويعود الفضل في ذلك إلى الطواقم التي أعادت فتح الأرصفة قبل الموعد المحدد، وإلى العملاء الذين ظلوا معنا طوال تلك الفترة.",
            "This review sets out what we delivered, what it cost and what we intend to change, in both of our working languages.",
            "وتعرض هذه المراجعة ما أنجزناه وما كلّفنا وما ننوي تغييره، باللغتين اللتين نعمل بهما.",
            lambda b: photo(b, a["coast"], "The northern terminal at first light | المحطة الشمالية عند الفجر", "Authority archive", hero=True))
    section(b, "Operations | العمليات",
            "Container traffic grew by seven percent, led by the new weekly service to the eastern ports. Average ship turnaround fell to twenty-two hours.",
            "نمت حركة الحاويات بنسبة سبعة في المئة، مدفوعة بالخدمة الأسبوعية الجديدة إلى الموانئ الشرقية. وتراجع متوسط زمن بقاء السفن إلى اثنتين وعشرين ساعة.",
            "Bulk cargo held steady, while the passenger terminal welcomed its millionth traveller of the year in November.",
            "وحافظت البضائع السائبة على مستواها، واستقبلت محطة الركاب مسافرها المليون لهذا العام في شهر نوفمبر.",
            lambda b: b.metric_row([{"label": "Containers | حاويات", "value": "1.84m"}, {"label": "Ship calls | سفن", "value": "6,210"}, {"label": "Turnaround | زمن البقاء", "value": "22h"}]),
            bars("Containers, thousands | الحاويات بالألف", {"2022": 1490, "2023": 1610, "2024": 1720, "2025": 1840}),
            bars("Ship calls | عدد السفن", {"2022": 5400, "2023": 5720, "2024": 5980, "2025": 6210}))
    section(b, "Finance | المالية",
            "Revenue rose in line with volumes, and the storm repairs were met from the reserve set aside for that purpose.",
            "ارتفعت الإيرادات بما يتناسب مع أحجام المناولة، وغُطيت إصلاحات العواصف من الاحتياطي المخصص لذلك.",
            table(["Item", "2025", "2024", "2023", "البند"],
                  [["Port dues", "412.6", "388.1", "361.4", "رسوم الموانئ"], ["Handling income", "298.3", "281.9", "264.0", "إيرادات المناولة"],
                   ["Property rent", "86.5", "82.2", "79.8", "إيجارات العقارات"], ["Operating costs", "(517.9)", "(489.4)", "(466.2)", "تكاليف التشغيل"],
                   ["Storm repairs", "(31.4)", "-", "-", "إصلاحات العواصف"]],
                  caption="Income statement, million | قائمة الدخل بالمليون", footer=["Surplus", "248.1", "262.8", "239.0", "الفائض"]),
            table(["Item", "2025", "2024", "البند"],
                  [["Cash and deposits", "640.2", "598.7", "النقد والودائع"], ["Port assets", "4,118.0", "3,962.5", "أصول الموانئ"], ["Borrowings", "(902.4)", "(948.1)", "القروض"]],
                  caption="Financial position, million | المركز المالي بالمليون", footer=["Net assets", "3,855.8", "3,613.1", "صافي الأصول"]))
    section(b, "People and safety | الأفراد والسلامة",
            "No serious injury was recorded for the second year running. Women now hold one in five operational roles, up from one in nine five years ago.",
            "لم تُسجل أي إصابة خطيرة للعام الثاني على التوالي. وتشغل النساء الآن وظيفة من كل خمس وظائف تشغيلية، بعد أن كانت واحدة من كل تسع قبل خمس سنوات.",
            lambda b: photo(b, a["works"], "Apprentices in the crane workshop | المتدربون في ورشة الرافعات", "Authority archive"),
            "The apprenticeship scheme took on sixty new starters, and for the first time it included training in both languages at every grade.",
            "استقبل برنامج التدريب ستين متدربًا جديدًا، وشمل لأول مرة تدريبًا باللغتين في جميع المستويات.")
    return b, {"name": "Northern Ports Authority", "primary": "#173F5F", "accent": "#C99A2E", "logo": a["logo"]}


def bilingual_water_compact(a):
    b = DocumentBuilder()
    b.meta(title="The Two Rivers Compact | ميثاق النهرين", subject="Progress report 2025 | تقرير التقدم ٢٠٢٥", author="Two Rivers Water Council")
    section(b, "Why a compact | لماذا الميثاق",
            "Seven towns share two rivers, and none of them can manage the water alone. The compact gives each town a fair allocation and a seat at one table.",
            "تتقاسم سبع بلدات نهرين، ولا تستطيع أي منها إدارة الماء بمفردها. ويمنح الميثاق كل بلدة حصة عادلة ومقعدًا على طاولة واحدة.",
            "Three years on, the council can report that withdrawals have fallen while farm output has held steady.",
            "وبعد ثلاث سنوات، يستطيع المجلس أن يعلن تراجع كميات السحب مع ثبات الإنتاج الزراعي.")
    section(b, "Allocations | الحصص",
            "Every town stayed within its allocation for the first time. Metering now covers nine in ten farm intakes, so the figures below are measured rather than estimated.",
            "التزمت كل البلدات بحصصها لأول مرة. وتغطي العدادات الآن تسعة من كل عشرة مآخذ زراعية، فالأرقام أدناه مقيسة لا مقدّرة.",
            table(["Use", "2025", "2024", "الاستخدام"],
                  [["Farming", "212", "231", "الزراعة"], ["Towns", "64", "66", "البلدات"], ["Industry", "18", "21", "الصناعة"], ["River flow reserve", "96", "78", "احتياطي جريان النهر"]],
                  caption="Allocation by use, million cubic metres | الحصص حسب الاستخدام بالمليون متر مكعب", footer=["Total", "390", "396", "الإجمالي"]),
            line("Withdrawals | كميات السحب", {"2022": 342, "2023": 331, "2024": 318, "2025": 294}),
            line("Farm output index | مؤشر الإنتاج الزراعي", {"2022": 100, "2023": 101, "2024": 99, "2025": 102}))
    section(b, "The rivers themselves | النهران",
            "Summer flow at the lower gauge rose by a quarter, and the first trout in twenty years were recorded above the old weir.",
            "ارتفع الجريان الصيفي عند المقياس السفلي بمقدار الربع، وسُجلت أول أسماك سلمون مرقط منذ عشرين عامًا فوق السد القديم.",
            lambda b: photo(b, a["coast2"], "The lower gauge in August | المقياس السفلي في أغسطس", "Council archive"),
            "Replanting along the banks continues, and landowners have now fenced forty kilometres of riverside against cattle.",
            "ويتواصل التشجير على الضفتين، وقد سيّج ملاك الأراضي حتى الآن أربعين كيلومترًا من ضفاف النهر لحمايتها من الماشية.")
    section(b, "Next steps | الخطوات القادمة",
            "The council will review allocations next spring, using three full years of measured data for the first time.",
            "سيراجع المجلس الحصص في الربيع القادم، مستندًا لأول مرة إلى بيانات مقيسة لثلاث سنوات كاملة.",
            "Two more towns have asked to join the compact, and their request will go to a public hearing in each of the seven towns.",
            "وقد طلبت بلدتان أخريان الانضمام إلى الميثاق، وسيُعرض طلبهما في جلسة علنية في كل بلدة من البلدات السبع.")
    return b, {"name": "Two Rivers Water Council", "primary": "#1F5F6B", "accent": "#8A6D3B", "logo": a["logo"]}


DOCUMENTS = {
    "annual_report": annual_report, "financial_statements": financial_statements, "board_paper": board_paper,
    "technical_manual": technical_manual, "research_paper": research_paper, "proposal": proposal,
    "impact_report": impact_report, "policy_brief": policy_brief, "arabic_annual": arabic_annual,
    "arabic_financial": arabic_financial, "bilingual_institutional": bilingual_institutional,
    "sustainability_report": sustainability_report, "harbour_feature": harbour_feature,
    "transit_data_story": transit_data_story, "arabic_city_feature": arabic_city_feature,
    "arabic_health_data": arabic_health_data, "bilingual_ports_review": bilingual_ports_review,
    "bilingual_water_compact": bilingual_water_compact,
}
